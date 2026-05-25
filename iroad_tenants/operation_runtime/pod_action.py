"""POD birth and posting side effects triggered from action logs."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone

from iroad_tenants.operation_runtime.constants import (
    SHIPMENT_POD_AUTO_FORM_CODE,
    SHIPMENT_POD_AUTO_FORM_LABEL,
    SHIPMENT_POD_REF_PREFIX,
)
from iroad_tenants.operation_runtime.impacts import operation_action_matches
from tenant_workspace.models import (
    TenantShipment,
    TenantShipmentDocument,
    TenantShipmentPodPage,
)


def birth_pod_from_action_log(action_log, *, created_by_label=''):
    """Action 7 / auto_pod_post — one POD record per delivery-note document."""
    shipment = action_log.shipment
    if shipment is None:
        return None
    source_document = (
        TenantShipmentDocument.objects.filter(
            shipment=shipment,
            is_delivery_note=True,
        )
        .order_by('-created_at')
        .first()
    )
    if source_document is None:
        raise ValidationError(
            'Auto POD Post requires at least one delivery-note document on the shipment.'
        )
    existing_pod = TenantShipmentDocument.objects.filter(
        source_document_id=source_document.pk,
    ).first()
    if existing_pod is not None:
        return existing_pod

    from iroad_tenants.views import (
        _next_auto_number_for_form,
        _tenant_shipment_document_apply_foreign_keys,
        _tenant_shipment_pod_build_line_rows_from_source,
        _tenant_shipment_pod_page_label,
        _tenant_shipment_pod_resolve_line_source_page,
    )

    record_no, record_sequence = _next_auto_number_for_form(
        form_code=SHIPMENT_POD_AUTO_FORM_CODE,
        form_label=SHIPMENT_POD_AUTO_FORM_LABEL,
        prefix=SHIPMENT_POD_REF_PREFIX,
    )
    document = TenantShipmentDocument(
        record_no=record_no,
        record_sequence=record_sequence,
        record_date=timezone.localdate(),
        document_type='pod',
        document_ref_no=source_document.document_ref_no,
        document_date=source_document.document_date or timezone.localdate(),
        physical_location='With Driver',
        page_count=source_document.page_count or 1,
        status=TenantShipmentDocument.Status.DRAFT,
        source_document=source_document,
        created_by_label=(created_by_label or '')[:200],
    )
    _tenant_shipment_document_apply_foreign_keys(
        document,
        booking=shipment.booking if shipment.booking_id else None,
        shipment=shipment,
    )
    document.save()

    line_payload = _tenant_shipment_pod_build_line_rows_from_source(source_document)
    TenantShipmentPodPage.objects.filter(document=document).delete()
    for idx, row in enumerate(line_payload, start=1):
        if not isinstance(row, dict):
            continue
        source_page = _tenant_shipment_pod_resolve_line_source_page(
            row.get('doc_page'),
            source_document,
            {},
        )
        TenantShipmentPodPage.objects.create(
            document=document,
            line_no=idx,
            source_page=source_page,
            doc_page=_tenant_shipment_pod_page_label(source_page)
            if source_page
            else row.get('doc_page', ''),
            source=row.get('source') or 'Action Log',
            action_log=row.get('action_log') or action_log.log_no,
            physical_location=row.get('physical_location') or 'With Driver',
            soft_copy_status=row.get('soft_copy_status') or 'Not Collected',
            digital_evidence_status=row.get('digital_evidence_status') or 'Not Collected',
            map_url=row.get('map_url') or '',
            attachment_label=row.get('attachment_label') or '',
        )

    if operation_action_matches(
        action_log.operation_action,
        'upload pod',
        'a7',
        'action 7',
    ):
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        shipment.save(update_fields=['pod_type', 'updated_at'])

    return document


def apply_pod_posting_from_action_log(
    *,
    action_log,
    pod_document,
    shipment,
    created_by_label: str = '',
) -> None:
    """Verify POD document and apply portal posting effects when A7 fires."""
    from iroad_tenants.views import _tenant_shipment_pod_apply_posting_effects

    action = action_log.operation_action
    if pod_document is None or action is None or shipment is None:
        return
    if not operation_action_matches(action, 'upload pod', 'a7', 'action 7'):
        return
    _tenant_shipment_pod_apply_posting_effects(
        document=pod_document,
        source_document=pod_document.source_document,
        shipment=shipment,
        header_physical_location='with_driver',
    )
    pod_document.save(update_fields=['status', 'physical_location', 'updated_at'])
