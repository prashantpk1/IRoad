"""
mobile_api/pod_capture/services/pod_evidence_adapter.py

Bridge ``PodCaptureContext`` to execution evidence validators (no duplicated rules).
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.action_log_media_persistence import ActionLogMediaItem
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput
from mobile_api.pod_capture.exceptions import PodCaptureError


def media_items_to_action_log_rows(
    items: list[PODCaptureMediaItemInput],
) -> list[ActionLogMediaItem]:
    rows: list[ActionLogMediaItem] = []
    for item in items:
        rows.append(
            ActionLogMediaItem(
                media_type=item.media_type,
                description=item.description,
                captured_at=item.captured_at,
                file_ref=item.file_ref,
                file_name=item.file_name,
                line_no=item.line_no,
                upload=item.upload,
            )
        )
    return rows


def build_execute_payload(context: PodCaptureContext) -> dict[str, Any]:
    media = []
    for item in context.media_items or []:
        media.append(
            {
                'media_type': item.media_type,
                'file_ref': item.file_ref,
                'file_name': item.file_name,
                'description': item.description,
                'captured_at': item.captured_at.isoformat()
                if item.captured_at and hasattr(item.captured_at, 'isoformat')
                else item.captured_at,
                'checksum': item.checksum,
                'sort_order': item.line_no,
            }
        )
    payload: dict[str, Any] = {
        'latitude': context.latitude,
        'longitude': context.longitude,
        'notes': context.notes,
        'media': media,
    }
    if context.latitude and context.longitude:
        try:
            payload['latitude'] = float(context.latitude)
            payload['longitude'] = float(context.longitude)
        except (TypeError, ValueError):
            pass
    return payload


def to_execute_action_context(context: PodCaptureContext) -> ExecuteActionContext:
    """Minimal execute context for ``EvidenceValidationService`` delegation."""
    return ExecuteActionContext(
        driver=context.driver,
        tenant_schema=context.tenant_schema,
        user_id=context.user_id or '',
        job_type='shipment',
        job_id=context.shipment_id,
        action_code=(context.target_action_code or '').strip(),
        shipment=context.shipment,
        booking=context.booking,
        operation_action=context.operation_action,
        payload=build_execute_payload(context),
        idempotent_replay=context.idempotent_replay,
    )


def map_execute_error(exc: ExecuteActionError) -> PodCaptureError:
    return PodCaptureError(
        str(exc),
        code=exc.code,
        http_status=exc.http_status,
        message_key=(
            f'mobile.pod_capture.{exc.code}'
            if exc.code
            else exc.message_key.replace('mobile.jobs.execute.', 'mobile.pod_capture.', 1)
        ),
        refresh_required=exc.refresh_required,
        validation_error=exc.validation_error,
    )
