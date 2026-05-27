"""
mobile_api/pod_capture/repositories/bundle_mappers.py

Map ORM rows ↔ staging dataclasses (API contract unchanged).
"""
from __future__ import annotations

from django.utils import timezone

from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
)
from mobile_api.pod_capture.models import PODCaptureBundle as BundleORM
from mobile_api.pod_capture.models import PODCaptureMedia as MediaORM


def bundle_orm_to_dto(row: BundleORM) -> PODCaptureBundle:
    status_raw = (row.bundle_status or 'draft').strip().lower()
    try:
        status = PODCaptureBundleStatus(status_raw)
    except ValueError:
        status = PODCaptureBundleStatus.DRAFT

    return PODCaptureBundle(
        bundle_id=str(row.id),
        client_capture_id=row.client_capture_id,
        shipment_id=row.shipment_id,
        driver_id=row.driver_id,
        tenant_schema=row.tenant_schema,
        status=status,
        content_hash=row.content_hash or '',
        media_count=row.media_count or 0,
        expires_at=row.expires_at,
        promoted_at=row.promoted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        promotion_action_log_id=(row.promotion_action_log_id or '').strip() or None,
        rejected_reason=row.rejected_reason or '',
        workflow_version=row.workflow_version or '',
        pod_type=row.pod_type or '',
        notes=row.notes or '',
        latitude=row.latitude or '',
        longitude=row.longitude or '',
        integrity_checksum=row.integrity_checksum or '',
        capture_device_id=row.capture_device_id or '',
        capture_app_version=row.capture_app_version or '',
        replayed_from_bundle_id=(
            str(row.replayed_from_bundle_id) if row.replayed_from_bundle_id else None
        ),
    )


def bundle_dto_to_orm_defaults(bundle: PODCaptureBundle) -> dict:
    replay_uuid = None
    if getattr(bundle, 'replayed_from_bundle_id', None):
        replay_uuid = bundle.replayed_from_bundle_id

    return {
        'id': bundle.bundle_id,
        'tenant_schema': bundle.tenant_schema,
        'shipment_id': bundle.shipment_id,
        'driver_id': bundle.driver_id,
        'client_capture_id': bundle.client_capture_id,
        'workflow_version': getattr(bundle, 'workflow_version', '') or '',
        'content_hash': bundle.content_hash or '',
        'bundle_status': bundle.status.value,
        'pod_type': getattr(bundle, 'pod_type', '') or '',
        'notes': getattr(bundle, 'notes', '') or '',
        'latitude': getattr(bundle, 'latitude', '') or '',
        'longitude': getattr(bundle, 'longitude', '') or '',
        'media_count': bundle.media_count,
        'expires_at': bundle.expires_at,
        'promoted_at': bundle.promoted_at,
        'promotion_action_log_id': bundle.promotion_action_log_id or '',
        'replayed_from_bundle_id': replay_uuid,
        'integrity_checksum': getattr(bundle, 'integrity_checksum', '') or '',
        'capture_device_id': getattr(bundle, 'capture_device_id', '') or '',
        'capture_app_version': getattr(bundle, 'capture_app_version', '') or '',
        'rejected_reason': bundle.rejected_reason or '',
        'created_at': bundle.created_at,
    }


def media_orm_to_dto(row: MediaORM) -> PODCaptureMedia:
    return PODCaptureMedia(
        media_id=str(row.id),
        bundle_id=str(row.bundle_id),
        shipment_id=row.shipment_id,
        driver_id=row.driver_id,
        tenant_schema=row.tenant_schema,
        client_capture_id=row.client_capture_id,
        media_type=row.media_type or '',
        file_ref=row.file_ref,
        mime_type=row.mime_type or '',
        uploaded_at=row.uploaded_at,
        checksum=row.checksum or '',
        line_no=row.line_no,
        file_name=row.file_name or '',
        description=row.description or '',
        captured_at=row.captured_at,
        promoted=row.promoted,
        immutable=row.immutable,
        promoted_at=row.promoted_at,
        promoted_action_log_id=(row.promoted_action_log_id or '').strip() or None,
    )


def media_dto_to_orm_defaults(row: PODCaptureMedia, *, bundle_pk: str) -> dict:
    return {
        'id': row.media_id,
        'bundle_id': bundle_pk,
        'tenant_schema': row.tenant_schema,
        'shipment_id': row.shipment_id,
        'driver_id': row.driver_id,
        'client_capture_id': row.client_capture_id,
        'media_type': row.media_type,
        'file_ref': row.file_ref,
        'mime_type': getattr(row, 'mime_type', '') or '',
        'checksum': row.checksum or '',
        'line_no': row.line_no,
        'file_name': row.file_name,
        'description': row.description,
        'captured_at': row.captured_at,
        'uploaded_at': row.uploaded_at or timezone.now(),
        'immutable': getattr(row, 'immutable', False),
        'promoted': row.promoted,
        'promoted_at': getattr(row, 'promoted_at', None),
        'promoted_action_log_id': getattr(row, 'promoted_action_log_id', '') or '',
    }
