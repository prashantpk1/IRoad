"""Shipment POD form helpers (PCS §5)."""
from __future__ import annotations

from django.db.models import Prefetch, Q

from iroad_tenants.shipment_pod_evidence import (
    action_log_attachment_meta_from_media,
    action_log_attachment_storage_path_from_media,
    action_log_map_url,
)
from tenant_workspace.models import (
    TenantOperationActionLog,
    TenantOperationActionMedia,
    TenantShipment,
    TenantShipmentDocument,
)


def action_log_attachment_storage_path(log) -> str:
    """Return storage path for the first media evidence row on an action log."""
    if log is None:
        return ''
    media_rows = getattr(log, '_prefetched_media', None)
    if media_rows is None:
        media_rows = list(
            TenantOperationActionMedia.objects.filter(action_log=log).order_by('line_no')[:1]
        )
    return action_log_attachment_storage_path_from_media(media_rows)


def action_log_attachment_meta(log) -> tuple[str, str]:
    """Return (label, url) for the first media evidence row on an action log."""
    if log is None:
        return '', ''
    media_rows = getattr(log, '_prefetched_media', None)
    if media_rows is None:
        media_rows = list(
            TenantOperationActionMedia.objects.filter(action_log=log).order_by('line_no')[:1]
        )
    return action_log_attachment_meta_from_media(media_rows)


def delivery_note_doc_no_options(*, include_document_id=None):
    """Delivery-note Shipment Documents for Doc No (PCS §5.1 / §5.2)."""
    qs = (
        TenantShipmentDocument.objects.filter(is_delivery_note=True)
        .select_related('shipment', 'booking', 'shipment__booking')
        .order_by('-created_at')
    )
    if include_document_id:
        qs = TenantShipmentDocument.objects.filter(
            Q(is_delivery_note=True) | Q(pk=include_document_id)
        ).select_related('shipment', 'booking', 'shipment__booking').order_by('-created_at')
    options = []
    for row in qs[:500]:
        shipment = row.shipment if row.shipment_id else None
        booking = row.booking
        if booking is None and shipment and shipment.booking_id:
            booking = shipment.booking
        booking_item = (shipment.booking_item_ref or '').strip() if shipment else ''
        pod_type = ''
        pod_status = TenantShipment.PodStatus.NOT_COMPLETED
        if shipment:
            from iroad_tenants.operation_field_catalog import normalize_operation_pod_status
            from iroad_tenants.views import _normalize_shipment_pod_type

            pod_type = _normalize_shipment_pod_type(
                shipment.pod_type or getattr(booking, 'pod_type', ''),
                default=TenantShipment.PodType.DIGITAL,
            )
            pod_status = normalize_operation_pod_status(
                shipment.pod_status,
                default=TenantShipment.PodStatus.NOT_COMPLETED,
            )
        record_no = (row.record_no or '').strip()
        document_ref_no = (row.document_ref_no or '').strip()
        options.append(
            {
                'document_id': str(row.pk),
                'record_no': record_no,
                'document_ref_no': document_ref_no,
                'display_label': f'{record_no} — {document_ref_no}'.strip(' —'),
                'shipment_id': str(row.shipment_id) if row.shipment_id else '',
                'shipment_no': shipment.shipment_no if shipment else '',
                'booking_id': str(booking.pk) if booking else '',
                'booking_no': booking.booking_no if booking else '',
                'booking_item': booking_item,
                'pod_type': pod_type,
                'pod_status': pod_status,
                'document_type': row.document_type or '',
                'document_date': row.document_date.isoformat() if row.document_date else '',
                'page_count': row.page_count or 1,
            }
        )
    return options


def doc_ref_options_map():
    """Doc Ref values keyed by Doc No (source document id)."""
    result: dict[str, list[dict]] = {}
    qs = TenantShipmentDocument.objects.filter(is_delivery_note=True).prefetch_related(
        'document_pages'
    )
    for document in qs.order_by('-created_at')[:500]:
        refs: list[dict] = []
        seen: set[str] = set()
        header_ref = (document.document_ref_no or '').strip()
        if header_ref and header_ref.upper() != 'PENDING':
            refs.append({'value': header_ref, 'label': header_ref})
            seen.add(header_ref)
        for page in document.document_pages.order_by('line_no'):
            page_ref = (page.doc_ref_no or '').strip()
            if page_ref and page_ref not in seen:
                refs.append({'value': page_ref, 'label': page_ref})
                seen.add(page_ref)
        if not refs:
            fallback = header_ref or document.record_no
            refs.append({'value': fallback, 'label': fallback})
        result[str(document.pk)] = refs
    return result


def apply_doc_no_linkage(form_data: dict, form_errors: dict):
    """
    Resolve delivery-note identity from Doc No (PCS §5.3).

    Document Info (ref, type, date, page count) comes from the selected DN.
    Booking/shipment, POD status, and POD page lines are filled manually in the portal.
    """
    doc_id = (form_data.get('doc_no') or form_data.get('source_document_id') or '').strip()
    if not doc_id:
        form_errors['doc_no'] = 'Doc No is required.'
        return None
    document = (
        TenantShipmentDocument.objects.filter(pk=doc_id, is_delivery_note=True)
        .select_related('shipment', 'booking', 'shipment__booking')
        .first()
    )
    if document is None:
        form_errors['doc_no'] = 'Select a valid delivery note (Doc No).'
        return None
    form_data['doc_no'] = str(document.pk)
    form_data['source_document_id'] = str(document.pk)
    if document.shipment_id is None:
        form_errors['doc_no'] = 'Selected document is not linked to a shipment.'
        return document
    selected_ref = (form_data.get('document_ref_no') or '').strip()
    if not selected_ref:
        header_ref = (document.document_ref_no or '').strip()
        if header_ref.upper() == 'PENDING':
            header_ref = ''
        form_data['document_ref_no'] = header_ref
    if not (form_data.get('document_type') or '').strip():
        form_data['document_type'] = document.document_type or 'delivery_note'
    if not (form_data.get('document_date') or '').strip() and document.document_date:
        form_data['document_date'] = document.document_date.isoformat()
    if not (form_data.get('page_count') or '').strip():
        form_data['page_count'] = str(document.page_count or 1)
    return document


def action_log_option_rows(*, shipment=None, limit=300):
    """Action log dropdown rows filtered on header shipment (PCS §5.6.1)."""
    qs = (
        TenantOperationActionLog.objects.select_related('operation_action')
        .prefetch_related(
            Prefetch(
                'media_rows',
                queryset=TenantOperationActionMedia.objects.order_by('line_no'),
                to_attr='_prefetched_media',
            )
        )
        .order_by('-log_date', '-created_at')
    )
    if shipment is not None:
        qs = qs.filter(shipment=shipment)
    rows = []
    for log in qs[:limit]:
        from iroad_tenants.views import _tenant_operation_action_log_action_label

        attachment_label, attachment_url = action_log_attachment_meta(log)
        rows.append(
            {
                'log_id': str(log.log_id),
                'log_no': log.log_no,
                'label': f'{log.log_no} — {_tenant_operation_action_log_action_label(log)}',
                'shipment_id': str(log.shipment_id) if log.shipment_id else '',
                'map_url': action_log_map_url(log),
                'attachment_label': attachment_label,
                'attachment_url': attachment_url,
                'attachment_storage_path': action_log_attachment_storage_path(log),
            }
        )
    return rows
