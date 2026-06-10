"""
mobile_api/pod_capture/services/pod_capture_media_service.py

Normalize and secure POD media for staging.

MIME, extension, size, and storage checks delegate to
:class:`~mobile_api.execution.evidence.execution_media_security.ExecutionMediaSecurityService`
via :class:`~mobile_api.pod_capture.guards.pod_capture_security_guard.PodCaptureSecurityGuard`
(tenant/shipment scoped paths — not generic execute paths).
"""
from __future__ import annotations

import mimetypes

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from mobile_api.execution.evidence.execution_media_security import ExecutionMediaSecurityService
from mobile_api.utils.file_upload_handler import infer_media_type
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureMedia, PODCaptureMediaItemInput
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.guards.pod_capture_security_guard import PodCaptureSecurityGuard
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


class PodCaptureMediaService:
    """
    Map API ``media[]`` to scoped rows after execution-grade security validation.

    Upload ownership and path policy are enforced by ``PodCaptureSecurityGuard``
    (wraps ``ExecutionMediaSecurityService`` for MIME / size / storage object checks).
    """

    def __init__(
        self,
        *,
        staging: EvidenceStagingService | None = None,
        security_guard: PodCaptureSecurityGuard | None = None,
    ) -> None:
        self._staging = staging or EvidenceStagingService()
        self._security = security_guard or PodCaptureSecurityGuard(staging=self._staging)

    def secure_media_for_capture(
        self,
        context: PodCaptureContext,
    ) -> list[PODCaptureMediaItemInput]:
        """
        Validate upload ownership + MIME/size via execution media security, then return items.

        Raises:
            PodCaptureError: Security or validation failure.
        """
        if context.idempotent_replay:
            return list(context.media_items or [])
        return self._security.validate_media_items(context)

    def normalize_payload_media(
        self,
        raw_items: list | None,
    ) -> list[PODCaptureMediaItemInput]:
        if not raw_items:
            return []
        normalized: list[PODCaptureMediaItemInput] = []
        for idx, row in enumerate(raw_items):
            if not isinstance(row, dict):
                continue
            captured_at = None
            captured_raw = str(
                row.get('captured_at') or row.get('timestamp') or ''
            ).strip()
            if captured_raw:
                captured_at = parse_datetime(captured_raw)
                if captured_at is not None and timezone.is_naive(captured_at):
                    captured_at = timezone.make_aware(
                        captured_at,
                        timezone.get_current_timezone(),
                    )
            file_ref = str(row.get('file_ref') or '').strip()
            file_name = str(row.get('file_name') or '').strip()
            duration_raw = row.get('duration_seconds')
            duration_seconds = None
            if duration_raw is not None and str(duration_raw).strip() != '':
                try:
                    duration_seconds = float(duration_raw)
                except (TypeError, ValueError):
                    duration_seconds = None
            media_type = infer_media_type(
                explicit=str(row.get('media_type') or ''),
                file_ref=file_ref,
                file_name=file_name,
                duration_seconds=duration_seconds,
            )
            normalized.append(
                PODCaptureMediaItemInput(
                    media_type=media_type,
                    file_ref=file_ref,
                    file_name=file_name,
                    description=str(row.get('description') or '').strip(),
                    captured_at=captured_at,
                    checksum=str(row.get('checksum') or row.get('content_hash') or '').strip(),
                    line_no=int(row.get('sort_order') or row.get('line_no') or (idx + 1)),
                    duration_seconds=duration_seconds,
                    upload=row.get('file'),
                )
            )
        return normalized

    def build_staged_media_rows(
        self,
        context: PodCaptureContext,
        items: list[PODCaptureMediaItemInput],
    ) -> list[PODCaptureMedia]:
        bundle = context.bundle
        if bundle is None:
            raise PodCaptureError(
                'Bundle not initialized.',
                code='bundle_missing',
                http_status=500,
                message_key='mobile.pod_capture.bundle_missing',
            )

        if context.idempotent_replay:
            return list(context.staged_media or [])

        scope = self._staging.scope_from_context(context)
        now = timezone.now()
        rows: list[PODCaptureMedia] = []
        for item in items:
            file_ref = (item.file_ref or '').strip()
            if item.upload is not None and not file_ref:
                file_ref = str(getattr(item.upload, 'name', '') or '')
            mime = mimetypes.guess_type(file_ref)[0] or ''
            if item.upload is not None:
                mime = str(getattr(item.upload, 'content_type', '') or mime)
            resolved_type = infer_media_type(
                explicit=item.media_type,
                content_type=mime,
                file_ref=file_ref,
                file_name=item.file_name,
                duration_seconds=item.duration_seconds,
            )
            rows.append(
                PODCaptureMedia(
                    media_id=PODCaptureMedia.new_id(),
                    bundle_id=bundle.bundle_id,
                    shipment_id=scope.shipment_id,
                    driver_id=scope.driver_id,
                    tenant_schema=scope.tenant_schema,
                    client_capture_id=scope.client_capture_id,
                    media_type=resolved_type,
                    file_ref=file_ref,
                    mime_type=mime,
                    uploaded_at=now,
                    checksum=item.checksum,
                    line_no=item.line_no,
                    file_name=item.file_name,
                    description=item.description,
                    captured_at=item.captured_at,
                    promoted=False,
                )
            )
        return rows

    def populate_context_from_payload(self, context: PodCaptureContext) -> None:
        payload = dict(context.payload or {})
        context.client_capture_id = str(payload.get('client_capture_id') or '').strip()
        context.content_hash = str(payload.get('content_hash') or '').strip()
        context.workflow_version = str(payload.get('workflow_version') or '').strip()
        context.target_action_code = str(
            payload.get('target_action_code') or payload.get('action_code') or ''
        ).strip()
        context.pod_capture_type = str(
            payload.get('pod_capture_type') or payload.get('pod_type') or ''
        ).strip()
        context.notes = str(payload.get('notes') or '').strip()
        lat = payload.get('latitude')
        lon = payload.get('longitude')
        context.latitude = '' if lat is None else str(lat)
        context.longitude = '' if lon is None else str(lon)
        context.media_items = self.normalize_payload_media(list(payload.get('media') or []))

    @staticmethod
    def execution_media_security() -> type[ExecutionMediaSecurityService]:
        """Expose execution media security for tests / documentation."""
        return ExecutionMediaSecurityService
