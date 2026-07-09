"""Auto-create Document Handover rows when mobile Hard POD custody is promoted."""
from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from tenant_workspace.models import (
    TenantDocumentHandover,
    TenantDocumentHandoverLine,
    TenantShipmentDocument,
    TenantShipmentDocumentPage,
    TenantShipmentPodPage,
)

MOBILE_HARD_POD_HANDOVER_NOTE_PREFIX = 'mobile_hard_pod_action_log:'
MOBILE_HANDOVER_POSTED_LOCATION = 'In Company'


def _handover_note_for_action_log(action_log_id: str) -> str:
    return f'{MOBILE_HARD_POD_HANDOVER_NOTE_PREFIX}{action_log_id}'


def _existing_handover_for_action_log(*, shipment, action_log_id: str) -> TenantDocumentHandover | None:
    if not action_log_id:
        return None
    note_marker = _handover_note_for_action_log(action_log_id)
    return (
        TenantDocumentHandover.objects.filter(
            shipment=shipment,
            notes__startswith=note_marker,
        )
        .order_by('-created_at')
        .first()
    )


def _confirmed_page_keys(confirmed_pages: list[dict[str, Any]] | None) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for row in list(confirmed_pages or []):
        if not isinstance(row, dict):
            continue
        page_id = str(row.get('page_id') or '').strip()
        if page_id:
            keys.add(('page_id', page_id))
            continue
        document_id = str(row.get('document_id') or '').strip()
        line_no = str(int(row.get('line_no') or 0))
        if document_id and line_no != '0':
            keys.add(('line', f'{document_id}:{line_no}'))
    return keys


def _page_collected(
    page: TenantShipmentDocumentPage,
    *,
    document_pk: str,
    confirmed_keys: set[tuple[str, str]],
) -> bool:
    page_key = ('page_id', str(page.pk))
    line_key = ('line', f'{document_pk}:{page.line_no}')
    return page_key in confirmed_keys or line_key in confirmed_keys


def _resolve_delivery_note(shipment) -> TenantShipmentDocument | None:
    document = (
        TenantShipmentDocument.objects.filter(shipment=shipment)
        .exclude(document_type__iexact='pod')
        .order_by('-created_at')
        .first()
    )
    if document is not None:
        return document
    if getattr(shipment, 'booking_id', None):
        return (
            TenantShipmentDocument.objects.filter(booking_id=shipment.booking_id)
            .exclude(document_type__iexact='pod')
            .order_by('-created_at')
            .first()
        )
    return None


def _resolve_pod_child(source_document: TenantShipmentDocument | None) -> TenantShipmentDocument | None:
    if source_document is None:
        return None
    return (
        TenantShipmentDocument.objects.filter(source_document=source_document)
        .order_by('-created_at')
        .first()
    )


def _handover_lines_all_received_ok(handover: TenantDocumentHandover) -> bool:
    lines = list(handover.lines.all())
    return bool(lines) and all(
        (line.page_status or '').strip() == 'ReceivedOK' for line in lines
    )


def _finalize_mobile_handover_posted(
    *,
    handover: TenantDocumentHandover,
    source_document: TenantShipmentDocument | None,
    shipment,
) -> TenantDocumentHandover:
    """Apply portal Posted effects when driver Hard POD custody is fully confirmed."""
    if handover.status == TenantDocumentHandover.Status.POSTED:
        return handover
    if not _handover_lines_all_received_ok(handover):
        return handover

    from iroad_tenants.views import _tenant_document_handover_apply_posting_effects

    handover.lines.filter(page_status='ReceivedOK').update(
        physical_location=MOBILE_HANDOVER_POSTED_LOCATION,
        updated_at=timezone.now(),
    )
    handover.physical_location = MOBILE_HANDOVER_POSTED_LOCATION
    _tenant_document_handover_apply_posting_effects(
        handover=handover,
        source_document=source_document or handover.document,
        shipment=shipment or handover.shipment,
    )
    handover.save(update_fields=['status', 'physical_location', 'updated_at'])
    return handover


def upgrade_stale_mobile_draft_handovers() -> int:
    """
    Post Draft mobile-born handovers that already have full ReceivedOK lines.

    Repairs legacy rows created before auto-post on Hard POD promotion.
    """
    upgraded = 0
    draft_handovers = (
        TenantDocumentHandover.objects.filter(
            status=TenantDocumentHandover.Status.DRAFT,
            notes__startswith=MOBILE_HARD_POD_HANDOVER_NOTE_PREFIX,
        )
        .select_related('shipment', 'document')
        .prefetch_related('lines')
    )
    for handover in draft_handovers:
        if not _handover_lines_all_received_ok(handover):
            continue
        _finalize_mobile_handover_posted(
            handover=handover,
            source_document=handover.document,
            shipment=handover.shipment,
        )
        upgraded += 1
    return upgraded


def _resolve_pod_line_for_dn_page(
    *,
    pod_document: TenantShipmentDocument | None,
    dn_page: TenantShipmentDocumentPage,
) -> TenantShipmentPodPage | None:
    if pod_document is None:
        return None
    return (
        TenantShipmentPodPage.objects.filter(
            document=pod_document,
            line_no=dn_page.line_no,
        )
        .first()
    )


def ensure_document_handover_from_hard_pod_promotion(
    *,
    shipment,
    action_log,
    confirmed_pages: list[dict[str, Any]] | None = None,
    custody_submission: Any | None = None,
    created_by_label: str = '',
) -> TenantDocumentHandover | None:
    """
    Birth a Document Handover when driver Hard POD custody is promoted.

    When every page is ReceivedOK the handover is auto-posted (Collected) so the
    portal list reflects completed mobile custody without a manual office step.
    Idempotent per promotion action log.
    """
    from iroad_tenants.operation_runtime.proof_pipeline import document_handover_allowed
    from iroad_tenants.views import (
        DOCUMENT_HANDOVER_AUTO_FORM_CODE,
        DOCUMENT_HANDOVER_AUTO_FORM_LABEL,
        DOCUMENT_HANDOVER_REF_PREFIX,
        _next_auto_number_for_form,
        _tenant_shipment_pod_page_label,
    )

    if shipment is None or action_log is None:
        return None
    if not document_handover_allowed(shipment):
        return None

    action_log_id = str(
        getattr(action_log, 'log_id', None) or getattr(action_log, 'pk', '') or ''
    ).strip()
    if not action_log_id:
        return None

    source_document = _resolve_delivery_note(shipment)
    if source_document is None:
        return None

    existing = _existing_handover_for_action_log(
        shipment=shipment,
        action_log_id=action_log_id,
    )
    if existing is not None:
        return _finalize_mobile_handover_posted(
            handover=existing,
            source_document=source_document,
            shipment=shipment,
        )

    pod_document = _resolve_pod_child(source_document)
    confirmed_keys = _confirmed_page_keys(confirmed_pages)
    dn_pages = list(source_document.document_pages.order_by('line_no'))
    if not dn_pages:
        return None

    line_payload: list[dict[str, Any]] = []
    for dn_page in dn_pages:
        pod_line = _resolve_pod_line_for_dn_page(
            pod_document=pod_document,
            dn_page=dn_page,
        )
        collected = _page_collected(
            dn_page,
            document_pk=str(source_document.pk),
            confirmed_keys=confirmed_keys,
        )
        line_payload.append(
            {
                'source_page': pod_line,
                'doc_page': (
                    _tenant_shipment_pod_page_label(pod_line)
                    if pod_line is not None
                    else (dn_page.doc_ref_no or f'Page-{dn_page.line_no}')
                ),
                'page_status': 'ReceivedOK' if collected else 'Missing',
                'physical_location': 'With Driver' if collected else '',
                'note': (
                    ''
                    if collected
                    else 'Not confirmed during mobile Hard POD custody submit.'
                ),
            }
        )

    if not line_payload:
        return None
    if any(row['page_status'] != 'ReceivedOK' for row in line_payload):
        # Driver checklist requires every page — skip partial handover rows.
        return None

    receiver_label = ''
    if custody_submission is not None:
        receiver_label = str(
            getattr(custody_submission, 'receiver_name', None)
            or getattr(custody_submission, 'receiver_contact', None)
            or ''
        ).strip()
    if not receiver_label:
        receiver_label = (created_by_label or 'Mobile Driver').strip()

    booking = shipment.booking if getattr(shipment, 'booking_id', None) else None
    handover_date = timezone.localdate()
    log_date = getattr(action_log, 'log_date', None)
    if log_date is not None and hasattr(log_date, 'date'):
        handover_date = log_date.date()

    try:
        with transaction.atomic():
            handover_no = ''
            handover_sequence = 0
            for _ in range(10):
                handover_no, handover_sequence = _next_auto_number_for_form(
                    form_code=DOCUMENT_HANDOVER_AUTO_FORM_CODE,
                    form_label=DOCUMENT_HANDOVER_AUTO_FORM_LABEL,
                    prefix=DOCUMENT_HANDOVER_REF_PREFIX,
                )
                if not TenantDocumentHandover.objects.filter(handover_no=handover_no).exists():
                    break
            if TenantDocumentHandover.objects.filter(handover_no=handover_no).exists():
                return None

            handover = TenantDocumentHandover.objects.create(
                handover_no=handover_no,
                handover_sequence=handover_sequence,
                handover_date=handover_date,
                booking=booking,
                shipment=shipment,
                document=source_document,
                pod_document=pod_document,
                physical_location='With Driver',
                receiver_user=None,
                received_user=receiver_label[:120],
                status=TenantDocumentHandover.Status.DRAFT,
                notes=_handover_note_for_action_log(action_log_id),
                created_by_label=(created_by_label or 'Mobile Hard POD')[:200],
            )
            for idx, row in enumerate(line_payload, start=1):
                TenantDocumentHandoverLine.objects.create(
                    handover=handover,
                    line_no=idx,
                    source_page=row['source_page'],
                    doc_page=str(row['doc_page'] or '')[:64],
                    page_status=row['page_status'],
                    physical_location=str(row['physical_location'] or '')[:120],
                    note=str(row['note'] or '')[:255],
                )
            return _finalize_mobile_handover_posted(
                handover=handover,
                source_document=source_document,
                shipment=shipment,
            )
    except IntegrityError:
        existing = _existing_handover_for_action_log(
            shipment=shipment,
            action_log_id=action_log_id,
        )
        if existing is None:
            return None
        return _finalize_mobile_handover_posted(
            handover=existing,
            source_document=source_document,
            shipment=shipment,
        )
