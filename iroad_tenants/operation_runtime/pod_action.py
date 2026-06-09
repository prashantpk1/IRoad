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
    resolve_operation_action_log_for_pod,
    TenantShipment,
    TenantShipmentDocument,
    TenantShipmentDocumentPage,
    TenantShipmentPodPage,
)


def _shipment_requires_hard_pod_mode(shipment) -> bool:
    """Hard POD compliance must survive A7 digital evidence posting."""
    if shipment is None:
        return False
    current = (getattr(shipment, 'pod_type', None) or '').strip()
    if current == TenantShipment.PodType.HARD:
        return True
    booking = getattr(shipment, 'booking', None)
    if booking is None and getattr(shipment, 'booking_id', None):
        from tenant_workspace.models import TenantBooking

        booking = TenantBooking.objects.filter(pk=shipment.booking_id).only('pod_type').first()
    if booking is not None:
        booking_pod = (getattr(booking, 'pod_type', None) or '').strip()
        if booking_pod == TenantShipment.PodType.HARD:
            return True
    from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

    if _pending_hard_pod_custody_exists(shipment):
        return True
    return False


def apply_a7_shipment_pod_type_classification(shipment) -> None:
    """
    A7 records digital evidence; it must not downgrade Hard shipments to Digital.

    Hard POD mobile flow: digital capture (A7) then physical confirmation (A7H)
    while ``pod_type`` stays Hard for gating and custody submit.
    """
    if shipment is None:
        return
    if getattr(shipment, 'pk', None):
        shipment.refresh_from_db(fields=['pod_type', 'booking_id', 'updated_at'])
    if _shipment_requires_hard_pod_mode(shipment):
        if (getattr(shipment, 'pod_type', None) or '').strip() != TenantShipment.PodType.HARD:
            shipment.pod_type = TenantShipment.PodType.HARD
            shipment.save(update_fields=['pod_type', 'updated_at'])
        return
    current = (getattr(shipment, 'pod_type', None) or '').strip()
    if current == TenantShipment.PodType.HARD:
        return
    shipment.pod_type = TenantShipment.PodType.DIGITAL
    shipment.save(update_fields=['pod_type', 'updated_at'])


def birth_pod_from_action_log(action_log, *, created_by_label=''):
    """Action 7 / auto_pod_post — one POD record per delivery-note document."""
    shipment = action_log.shipment
    if shipment is None:
        return None
    is_upload_pod_action = operation_action_matches(
        action_log.operation_action,
        'upload pod',
        'a7',
        'action 7',
    )
    source_document = (
        TenantShipmentDocument.objects.filter(
            shipment=shipment,
            is_delivery_note=True,
        )
        .order_by('-created_at')
        .first()
    )
    if source_document is None:
        if is_upload_pod_action:
            source_document = _auto_create_delivery_note_for_a7(
                action_log,
                shipment=shipment,
                created_by_label=created_by_label,
            )
        else:
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
        action_log_value = row.get('action_log')
        action_log_obj = None
        if getattr(action_log_value, 'pk', None):
            action_log_obj = action_log_value
        else:
            action_log_obj = resolve_operation_action_log_for_pod(
                action_log_value,
                shipment=shipment,
            )
        TenantShipmentPodPage.objects.create(
            document=document,
            line_no=idx,
            source_page=source_page,
            doc_page=_tenant_shipment_pod_page_label(source_page)
            if source_page
            else row.get('doc_page', ''),
            source=row.get('source') or 'Action Log',
            action_log=action_log_obj,
            physical_location=row.get('physical_location') or 'With Driver',
            soft_copy_status=row.get('soft_copy_status') or 'Not Collected',
            digital_evidence_status=row.get('digital_evidence_status') or 'Not Collected',
            map_url=row.get('map_url') or '',
            attachment_label=row.get('attachment_label') or '',
        )

    if is_upload_pod_action:
        apply_a7_shipment_pod_type_classification(shipment)

    return document


def _auto_create_delivery_note_for_a7(action_log, *, shipment, created_by_label=''):
    """
    A7 mobile flow may stage POD evidence before office creates Shipment Document.
    Create a minimal delivery-note source so auto POD posting can proceed.
    """
    from iroad_tenants.views import (
        SHIPMENT_DOCUMENTS_AUTO_FORM_CODE,
        SHIPMENT_DOCUMENTS_AUTO_FORM_LABEL,
        SHIPMENT_DOCUMENTS_REF_PREFIX,
        _next_auto_number_for_form,
        _tenant_shipment_document_apply_foreign_keys,
    )

    record_no, record_sequence = _next_auto_number_for_form(
        form_code=SHIPMENT_DOCUMENTS_AUTO_FORM_CODE,
        form_label=SHIPMENT_DOCUMENTS_AUTO_FORM_LABEL,
        prefix=SHIPMENT_DOCUMENTS_REF_PREFIX,
    )
    source_document = TenantShipmentDocument(
        record_no=record_no,
        record_sequence=record_sequence,
        record_date=timezone.localdate(),
        document_type='delivery_note',
        document_ref_no=shipment.shipment_no or record_no,
        document_date=timezone.localdate(),
        is_delivery_note=True,
        physical_location='With Driver',
        page_count=1,
        status=TenantShipmentDocument.Status.UPLOADED,
        notes='Auto-created during A7 to satisfy POD source document requirement.',
        created_by_label=(created_by_label or '')[:200]
        or 'mobile_a7_auto_delivery_note',
    )
    _tenant_shipment_document_apply_foreign_keys(
        source_document,
        booking=shipment.booking if shipment.booking_id else None,
        shipment=shipment,
    )
    source_document.save()
    return source_document


def _apply_a7_hard_pod_digital_posting(
    *,
    action_log,
    pod_document,
    source_document,
    shipment,
) -> None:
    """
    Hard POD A7: digital evidence on POD child; update manual DN page completion.

    Does not relocate the delivery-note header to In Company — physical custody
    is confirmed later via A7H.
    """
    from iroad_tenants.views import _tenant_shipment_document_refresh_shipment_pod

    now = timezone.now()

    pod_document.physical_location = 'With Driver'
    pod_document.status = TenantShipmentDocument.Status.VERIFIED
    if not pod_document.record_date:
        pod_document.record_date = timezone.localdate()
    pod_document.save(
        update_fields=['physical_location', 'status', 'record_date', 'updated_at'],
    )

    action_log_obj = action_log if getattr(action_log, 'pk', None) else None
    for page in TenantShipmentPodPage.objects.filter(document=pod_document).order_by('line_no'):
        page.digital_evidence_status = 'Collected'
        if action_log_obj is not None and page.action_log_id is None:
            page.action_log = action_log_obj
        page.save(update_fields=['digital_evidence_status', 'action_log', 'updated_at'])

    if source_document is not None:
        TenantShipmentDocumentPage.objects.filter(document=source_document).update(
            completion_status=TenantShipmentDocumentPage.CompletionStatus.COMPLETED,
            updated_at=now,
        )
        source_document.refresh_from_db()
        source_document.sync_pod_pages_from_document_pages()

    if shipment is not None:
        _tenant_shipment_document_refresh_shipment_pod(shipment)


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
    source_document = pod_document.source_document
    if _shipment_requires_hard_pod_mode(shipment):
        _apply_a7_hard_pod_digital_posting(
            action_log=action_log,
            pod_document=pod_document,
            source_document=source_document,
            shipment=shipment,
        )
    else:
        _tenant_shipment_pod_apply_posting_effects(
            document=pod_document,
            source_document=source_document,
            shipment=shipment,
            header_physical_location='with_driver',
        )
        pod_document.save(update_fields=['status', 'physical_location', 'updated_at'])
    apply_a7_shipment_pod_type_classification(shipment)
