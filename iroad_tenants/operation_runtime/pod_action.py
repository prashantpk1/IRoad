"""POD birth and posting side effects triggered from action logs."""

from __future__ import annotations

import os
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

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


def _find_existing_pod_for_source(*, shipment, source_document):
    """Return an existing POD child for this delivery-note / shipment, if any."""
    if source_document is not None:
        existing = TenantShipmentDocument.objects.filter(
            source_document_id=source_document.pk,
        ).first()
        if existing is not None:
            return existing
    if shipment is not None:
        return (
            TenantShipmentDocument.objects.filter(
                shipment=shipment,
                document_type='pod',
            )
            .order_by('-created_at')
            .first()
        )
    return None


def _allocate_unique_pod_record_no() -> tuple[str, int]:
    """Allocate POD record_no; retry when auto-number sequence lags existing rows."""
    from iroad_tenants.views import _next_auto_number_for_form

    for _ in range(10):
        record_no, record_sequence = _next_auto_number_for_form(
            form_code=SHIPMENT_POD_AUTO_FORM_CODE,
            form_label=SHIPMENT_POD_AUTO_FORM_LABEL,
            prefix=SHIPMENT_POD_REF_PREFIX,
        )
        if not TenantShipmentDocument.objects.filter(record_no=record_no).exists():
            return record_no, record_sequence
    raise ValidationError(
        'Unable to allocate a unique POD Record No. Please check Auto Number Configuration.'
    )


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
    existing_pod = _find_existing_pod_for_source(
        shipment=shipment,
        source_document=source_document,
    )
    if existing_pod is not None:
        return existing_pod

    from iroad_tenants.views import (
        _tenant_shipment_document_apply_foreign_keys,
        _tenant_shipment_pod_build_line_rows_from_source,
        _tenant_shipment_pod_page_label,
        _tenant_shipment_pod_resolve_line_source_page,
    )

    record_no, record_sequence = _allocate_unique_pod_record_no()
    pod_user = getattr(action_log, 'created_by', None)
    pod_user_label = (created_by_label or '')[:200]
    if pod_user is not None:
        pod_user_label = (
            pod_user.username or pod_user.full_name or pod_user_label
        )[:200]
    else:
        from iroad_tenants.views import _tenant_operation_action_log_resolve_user

        resolved_user = _tenant_operation_action_log_resolve_user(created_by_label)
        if resolved_user is not None:
            pod_user_label = (
                resolved_user.username or resolved_user.full_name or pod_user_label
            )[:200]
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
        receiver_user=pod_user,
        created_by_label=pod_user_label,
    )
    _tenant_shipment_document_apply_foreign_keys(
        document,
        booking=shipment.booking if shipment.booking_id else None,
        shipment=shipment,
    )
    try:
        document.save()
    except IntegrityError:
        existing_pod = _find_existing_pod_for_source(
            shipment=shipment,
            source_document=source_document,
        )
        if existing_pod is None:
            existing_pod = TenantShipmentDocument.objects.filter(
                record_no=record_no,
            ).first()
        if existing_pod is not None:
            return existing_pod
        raise

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

    if shipment is not None:
        _tenant_shipment_document_refresh_shipment_pod(shipment)


def _action_log_media_storage_path(media_row: Any) -> str:
    uploaded = getattr(media_row, 'file', None)
    if uploaded and getattr(uploaded, 'name', None):
        return str(uploaded.name).strip()
    return ''


def _sync_a7_action_log_media_to_pod_pages(
    *,
    action_log,
    pod_document,
) -> None:
    """Promote A7 evidence (photo / video) onto POD page rows only — not delivery notes."""
    if action_log is None or pod_document is None:
        return
    media_manager = getattr(action_log, 'media_rows', None)
    if media_manager is None:
        return
    media_rows = list(media_manager.all().order_by('line_no', 'created_at'))
    if not media_rows:
        return

    photo_types = {'photo', 'signature', 'document'}
    video_types = {'video'}
    evidence_rows: list[tuple[str, str]] = []
    for media_row in media_rows:
        storage_path = _action_log_media_storage_path(media_row)
        if not storage_path:
            continue
        media_type = (getattr(media_row, 'media_type', None) or '').strip().casefold()
        if media_type not in photo_types | video_types:
            continue
        label = os.path.basename(storage_path) or (
            getattr(media_row, 'description', None) or ''
        ).strip()
        evidence_rows.append((storage_path, label[:255]))
    if not evidence_rows:
        return

    pod_lines = list(
        TenantShipmentPodPage.objects.filter(document=pod_document).order_by(
            'line_no',
            'created_at',
        )
    )
    action_log_obj = action_log if getattr(action_log, 'pk', None) else None
    for idx, (storage_path, label) in enumerate(evidence_rows, start=1):
        if idx <= len(pod_lines):
            pod_line = pod_lines[idx - 1]
        else:
            pod_line = TenantShipmentPodPage.objects.create(
                document=pod_document,
                line_no=idx,
                doc_page=f'Evidence-{idx}',
                source='Action Log',
                action_log=action_log_obj,
                physical_location='With Driver',
                soft_copy_status='Collected',
                digital_evidence_status='Not Collected',
            )
            pod_lines.append(pod_line)

        pod_line.map_url = storage_path
        pod_line.attachment_label = label
        pod_line.digital_evidence_status = 'Collected'
        if action_log_obj is not None:
            pod_line.action_log = action_log_obj
        pod_line.save(
            update_fields=[
                'map_url',
                'attachment_label',
                'digital_evidence_status',
                'action_log',
                'updated_at',
            ],
        )


def apply_a7h_hard_pod_physical_posting(
    *,
    action_log,
    shipment,
    confirmed_pages: list[dict] | None = None,
    tenant_schema: str = '',
) -> None:
    """
    After A7H custody execute: mark DN subform lines Collected / Not Collected.

    Confirmed checklist pages → ``Completed`` + ``Collected``; others stay open.
    """
    if shipment is None:
        return

    schema = (tenant_schema or '').strip()
    if not schema:
        active = (getattr(connection, 'schema_name', None) or '').strip()
        if active and active != get_public_schema_name():
            schema = active

    def _apply() -> None:
        _apply_a7h_hard_pod_physical_posting_body(
            action_log=action_log,
            shipment=shipment,
            confirmed_pages=confirmed_pages,
        )

    if schema:
        with schema_context(schema):
            _apply()
    else:
        _apply()


def _apply_a7h_hard_pod_physical_posting_body(
    *,
    action_log,
    shipment,
    confirmed_pages: list[dict] | None = None,
) -> None:
    from iroad_tenants.views import _tenant_shipment_document_refresh_shipment_pod

    if isinstance(shipment, TenantShipment):
        shipment = TenantShipment.objects.filter(pk=shipment.pk).first() or shipment

    confirmed_keys: set[tuple[str, str]] = set()
    for row in list(confirmed_pages or []):
        if not isinstance(row, dict):
            continue
        page_id = str(row.get('page_id') or '').strip()
        if page_id:
            confirmed_keys.add(('page_id', page_id))
            continue
        document_id = str(row.get('document_id') or '').strip()
        line_no = str(int(row.get('line_no') or 0))
        if document_id and line_no != '0':
            confirmed_keys.add(('line', f'{document_id}:{line_no}'))

    dn_documents = TenantShipmentDocument.objects.filter(
        shipment=shipment,
        is_delivery_note=True,
    )
    if not dn_documents.exists() and getattr(shipment, 'booking_id', None):
        dn_documents = TenantShipmentDocument.objects.filter(
            booking_id=shipment.booking_id,
            is_delivery_note=True,
        )

    for document in dn_documents.prefetch_related('document_pages'):
        pod_child = (
            TenantShipmentDocument.objects.filter(source_document=document)
            .order_by('-created_at')
            .first()
        )
        document_pages = list(document.document_pages.order_by('line_no'))
        all_pages_collected = bool(document_pages)
        for page in document_pages:
            page_key = ('page_id', str(page.pk))
            line_key = ('line', f'{document.pk}:{page.line_no}')
            collected = page_key in confirmed_keys or line_key in confirmed_keys
            if not collected:
                all_pages_collected = False
            if collected:
                page.completion_status = TenantShipmentDocumentPage.CompletionStatus.COMPLETED
                page.signer_location = TenantShipmentDocumentPage.SignerLocation.WITH_DRIVER
            else:
                page.completion_status = (
                    TenantShipmentDocumentPage.CompletionStatus.NOT_COMPLETED
                )
            page.save(
                update_fields=['completion_status', 'signer_location', 'updated_at'],
            )
            dn_pod_line = TenantShipmentPodPage.objects.filter(
                document=document,
                line_no=page.line_no,
            ).first()
            if dn_pod_line is not None:
                dn_pod_line.soft_copy_status = (
                    'Collected' if collected else 'Not Collected'
                )
                dn_pod_line.physical_location = (
                    TenantShipmentDocumentPage.SignerLocation.WITH_DRIVER
                    if collected
                    else ''
                )
                dn_pod_line.save(
                    update_fields=[
                        'soft_copy_status',
                        'physical_location',
                        'updated_at',
                    ],
                )
            if pod_child is not None:
                pod_line = TenantShipmentPodPage.objects.filter(
                    document=pod_child,
                    line_no=page.line_no,
                ).first()
                if pod_line is not None:
                    pod_line.soft_copy_status = 'Collected' if collected else 'Not Collected'
                    pod_line.physical_location = (
                        TenantShipmentDocumentPage.SignerLocation.WITH_DRIVER
                        if collected
                        else ''
                    )
                    if collected and action_log is not None:
                        pod_line.action_log = action_log
                    pod_line.save(
                        update_fields=[
                            'soft_copy_status',
                            'physical_location',
                            'action_log',
                            'updated_at',
                        ],
                    )
        # Do not call sync_pod_pages_from_document_pages() here — POD child lines
        # hold PROTECT FKs to DN pod_pages; delete-all sync raises ProtectedError.
        document.physical_location = 'With Driver'
        header_update_fields = ['physical_location', 'updated_at']
        if all_pages_collected:
            document.status = TenantShipmentDocument.Status.VERIFIED
            header_update_fields.append('status')
        document.save(update_fields=header_update_fields)

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
    _sync_a7_action_log_media_to_pod_pages(
        action_log=action_log,
        pod_document=pod_document,
    )
    apply_a7_shipment_pod_type_classification(shipment)
