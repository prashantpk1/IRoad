"""
3-layer proof pipeline rules (Shipment Documents → Shipment POD → Document Handover).

Shipment Documents subform rows are the source of truth for page count.
Shipment POD stores digital + soft evidence only.
Document Handover is hard-copy verification only (Hard POD shipments).
"""
from __future__ import annotations

from iroad_tenants.operation_field_catalog import (
    normalize_operation_pod_type,
    operation_shipment_uses_hard_copy_pod,
)
from tenant_workspace.models import TenantShipment

SINGLE_PAGE_MAX = 1


def shipment_pod_type(shipment, *, booking=None) -> str:
    if shipment is None:
        return ''
    booking = booking or getattr(shipment, 'booking', None)
    pod = normalize_operation_pod_type(getattr(shipment, 'pod_type', None), default='')
    if not pod and booking is not None:
        pod = normalize_operation_pod_type(getattr(booking, 'pod_type', None), default='')
    return pod


def is_digital_pod(shipment, *, booking=None) -> bool:
    return shipment_pod_type(shipment, booking=booking) == TenantShipment.PodType.DIGITAL


def requires_single_document_page(shipment, *, is_delivery_note: bool) -> bool:
    """Non-delivery-note documents → one subform row only."""
    return not is_delivery_note


def document_page_line_count(source_document) -> int:
    if source_document is None:
        return SINGLE_PAGE_MAX
    pages = list(source_document.document_pages.order_by('line_no'))
    if pages:
        return len(pages)
    return max(int(getattr(source_document, 'page_count', None) or 1), SINGLE_PAGE_MAX)


def expected_pod_page_line_count(source_document, shipment=None) -> int:
    """POD page rows must match Shipment Document subform row count."""
    if source_document is None:
        return SINGLE_PAGE_MAX
    is_dn = bool(getattr(source_document, 'is_delivery_note', False))
    count = document_page_line_count(source_document)
    if requires_single_document_page(shipment, is_delivery_note=is_dn):
        return SINGLE_PAGE_MAX
    return count


def apply_shipment_document_line_rules(
    *,
    shipment,
    is_delivery_note: bool,
    line_rows: list,
) -> tuple[list, dict[str, str]]:
    """Normalize and validate Shipment Document subform rows."""
    errors: dict[str, str] = {}
    rows = list(line_rows or [])
    if not rows:
        rows = [{}]

    if requires_single_document_page(shipment, is_delivery_note=is_delivery_note):
        if len(line_rows or []) > SINGLE_PAGE_MAX:
            errors['page_count'] = (
                'When Delivery Note is off, only one subform line is allowed.'
            )
        rows = rows[:SINGLE_PAGE_MAX]
    elif is_delivery_note and not rows:
        errors['page_count'] = 'Delivery note documents require at least one subform page.'

    return rows, errors


def validate_pod_page_line_count(
    *,
    source_document,
    shipment,
    line_count: int,
) -> str | None:
    expected = expected_pod_page_line_count(source_document, shipment)
    if line_count != expected:
        return (
            f'Shipment POD requires exactly {expected} page line(s) matching the '
            f'source document subform (received {line_count}).'
        )
    return None


def validate_manual_pod_page_lines(
    line_payload,
    *,
    is_posted: bool,
) -> dict[str, str]:
    """Action Log vs Manual rules on POD page lines (manual portal entry)."""
    errors: dict[str, str] = {}
    for idx, item in enumerate(line_payload, start=1):
        if isinstance(item, tuple):
            _line_no, values = item
        else:
            values = item
        source = str(values.get('source') or 'Action Log').strip()
        action_log = values.get('action_log')
        map_url = str(values.get('map_url') or '').strip()
        attachment_path = str(values.get('attachment_storage_path') or '').strip()

        if source == 'Manual':
            if action_log is not None:
                errors.setdefault(
                    'pod_pages',
                    f'Line {idx}: Action Log must be empty when source is Manual.',
                )
            if is_posted:
                if not map_url:
                    errors.setdefault(
                        'pod_pages',
                        f'Line {idx}: Map URL is required for manual POD pages.',
                    )
                if not attachment_path:
                    errors.setdefault(
                        'pod_pages',
                        f'Line {idx}: Attachment is required for manual POD pages.',
                    )
        elif is_posted and action_log is None:
            if not map_url and not attachment_path:
                errors.setdefault(
                    'pod_pages',
                    f'Line {idx}: select an Action Log or provide map URL / attachment.',
                )
    return errors


def document_handover_allowed(shipment) -> bool:
    """Document Handover is hard-copy chain of custody — Hard POD only."""
    return operation_shipment_uses_hard_copy_pod(shipment=shipment)


def shipment_auto_pod_document_flow(shipment) -> bool:
    """Shipment uses mobile auto POD post (requires manual delivery note in portal first)."""
    if shipment is None:
        return False
    return int(getattr(shipment, 'pod_doc_count', None) or 0) > 0


def shipment_existing_delivery_note(
    shipment,
    *,
    exclude_document_id=None,
):
    """Latest delivery-note header for a shipment, if any."""
    if shipment is None:
        return None
    from tenant_workspace.models import TenantShipmentDocument

    qs = TenantShipmentDocument.objects.filter(
        shipment=shipment,
        is_delivery_note=True,
    ).order_by('-created_at')
    if exclude_document_id:
        qs = qs.exclude(pk=exclude_document_id)
    return qs.first()


def validate_manual_shipment_document_create(
    *,
    shipment,
    is_delivery_note: bool,
    document_type: str = '',
    editing_document_id=None,
) -> str | None:
    """
    Block duplicate manual delivery-note create when one already exists on the shipment.

    Portal users create delivery notes manually; edit the existing row instead of adding another.
    """
    if shipment is None:
        return None
    doc_type = (document_type or '').strip().casefold().replace(' ', '_')
    creating_dn = bool(is_delivery_note) or doc_type in {
        'delivery_note',
        'deliverynote',
    }
    if not creating_dn:
        return None
    existing = shipment_existing_delivery_note(
        shipment,
        exclude_document_id=editing_document_id,
    )
    if existing is None:
        return None
    return (
        f'This shipment already has delivery note {existing.record_no}. '
        f'Edit the existing record instead of creating a duplicate.'
    )


def validate_handover_page_line_count(
    *,
    source_document,
    shipment,
    line_count: int,
) -> str | None:
    if not document_handover_allowed(shipment):
        return None
    expected = expected_pod_page_line_count(source_document, shipment)
    if line_count != expected:
        return (
            f'Document Handover requires exactly {expected} verification line(s) '
            f'matching the source document subform (received {line_count}).'
        )
    return None


POD_EVIDENCE_COLLECTED = 'Collected'


def _pod_pages_for_document(document) -> list:
    pod_pages = getattr(document, 'pod_pages', None)
    if pod_pages is None:
        return []
    if hasattr(pod_pages, 'all'):
        return list(pod_pages.all())
    return list(pod_pages)


def resolve_shipment_pod_evidence_display(document) -> dict[str, str]:
    """
    Shipment POD list badge — digital + soft evidence only (never Hard Copy).

    Hard POD shipments still show Digital Evidence / Soft Copy here; physical
    hard-copy verification belongs in Document Handover.
    """
    pages = _pod_pages_for_document(document)
    digital = any(
        (getattr(page, 'digital_evidence_status', '') or '').strip() == POD_EVIDENCE_COLLECTED
        for page in pages
    )
    soft = any(
        (getattr(page, 'soft_copy_status', '') or '').strip() == POD_EVIDENCE_COLLECTED
        for page in pages
    )

    if digital and soft:
        return {'evidence_type': 'Digital + Soft', 'evidence_badge': 'mixed'}
    if soft:
        return {
            'evidence_type': TenantShipment.PodType.SOFT,
            'evidence_badge': 'soft',
        }
    if digital:
        return {'evidence_type': 'Digital Evidence', 'evidence_badge': 'digital'}
    return {'evidence_type': 'Pending Evidence', 'evidence_badge': 'pending'}


def shipment_pod_list_stats(*, stats_qs, stats_shipment_qs) -> dict[str, int]:
    """Shipment POD list summary cards — count page evidence, not shipment.pod_type."""
    digital_count = (
        stats_qs.filter(pod_pages__digital_evidence_status=POD_EVIDENCE_COLLECTED)
        .distinct()
        .count()
    )
    soft_count = (
        stats_qs.filter(pod_pages__soft_copy_status=POD_EVIDENCE_COLLECTED)
        .distinct()
        .count()
    )
    pending_evidence = (
        stats_qs.exclude(pod_pages__digital_evidence_status=POD_EVIDENCE_COLLECTED)
        .exclude(pod_pages__soft_copy_status=POD_EVIDENCE_COLLECTED)
        .distinct()
        .count()
    )
    hard_pod_shipments = stats_shipment_qs.filter(
        pod_type=TenantShipment.PodType.HARD,
    ).count()
    return {
        'total': stats_qs.count(),
        'digital_evidence': digital_count,
        'soft_copy': soft_count,
        'hard_pod_shipments': hard_pod_shipments,
        'pending_evidence': pending_evidence,
        'completed': stats_shipment_qs.filter(
            pod_status=TenantShipment.PodStatus.COMPLETED,
        ).count(),
        'pending': stats_shipment_qs.filter(
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
        ).count(),
    }
