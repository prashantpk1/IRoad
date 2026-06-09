"""
mobile_api/execution/evidence/evidence_validation_service.py

Server-side enforcement of GPS / media / note requirements from Action Master metadata.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execution_validation_error import build_validation_error
from mobile_api.execution.evidence.constants import (
    ALLOWED_MEDIA_TYPES,
    EXECUTION_MEDIA_MAX_DOCUMENTS,
    EXECUTION_MEDIA_MAX_ITEMS,
    EXECUTION_MEDIA_MAX_PHOTOS,
    EXECUTION_MEDIA_MAX_VIDEOS,
    PHOTO_MEDIA_TYPES,
    VIDEO_MEDIA_TYPES,
)
from mobile_api.execution.evidence.action_log_media_persistence import normalize_media_items
from mobile_api.execution.evidence.execution_media_security import (
    ExecutionMediaSecurityService,
)
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.helpers.action_execution_metadata import build_execution_requirements
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_pod_upload_action,
)


def extract_capture_bundle_id(payload: dict[str, Any] | None) -> str:
    """Resolve staged POD bundle id from execute payload."""
    data = payload or {}
    for key in (
        'capture_bundle_id',
        'pod_capture_bundle_id',
        'bundle_id',
    ):
        token = str(data.get(key) or '').strip()
        if token:
            return token
    return ''


class EvidenceValidationService:
    """
    Validate required evidence before ``ActionExecutionService.execute_driver_action``.

    Rules derive from ``build_execution_requirements`` (same metadata as Job Detail UI).
    """

    def __init__(
        self,
        *,
        media_security: ExecutionMediaSecurityService | None = None,
    ) -> None:
        self._media_security = media_security or ExecutionMediaSecurityService()

    def validate_required_evidence(self, context: ExecuteActionContext) -> None:
        """
        Raises:
            ExecuteActionError: Missing or invalid evidence (HTTP 400).
        """
        if context.idempotent_replay:
            return

        operation_action = context.operation_action
        if operation_action is None:
            return

        payload = context.payload or {}
        bundle_id = self._auto_attach_staged_pod_bundle(context)
        if bundle_id:
            self.validate_pod_capture_bundle(context, bundle_id)
            requirements = dict(context.resolver_meta.get('pod_capture_compliance') or {})
            self._validate_gps(payload, requirements)
            self._validate_notes(payload, requirements)
            self._validate_media(context, requirements)
            self._attach_operational_issue_warnings(context)
            return

        requirements = build_execution_requirements(operation_action)
        self._validate_gps(payload, requirements)
        self._validate_notes(payload, requirements)
        self._media_security.validate_media(context)
        self._validate_media(context, requirements)
        self._attach_operational_issue_warnings(context)

    def validate_pod_capture_bundle(
        self,
        context: ExecuteActionContext,
        bundle_id: str,
    ) -> None:
        """
        Validate staged POD bundle before kernel execute (ownership, shipment, state).

        Does not promote — promotion runs after Action Log insert in orchestrator.
        """
        if context.job_type != 'shipment':
            raise self._evidence_error(
                error_code='pod_capture_shipment_only',
                message=str(_('mobile.jobs.execute.pod_capture_shipment_only')),
            )

        driver_pk = self._driver_pk(context.driver)
        shipment_key = self._shipment_key(context)
        if not shipment_key:
            raise self._evidence_error(
                error_code='job_not_found',
                message=str(_('mobile.jobs.not_found')),
                http_status=404,
            )

        try:
            from mobile_api.pod_capture.dto.promotion_models import PodPromotionScope
            from mobile_api.pod_capture.exceptions import PodCaptureError
            from mobile_api.pod_capture.policy.pod_capture_policy import (
                build_pod_capture_requirements,
            )
            from mobile_api.pod_capture.services.pod_capture_bundle_service import (
                PodCaptureBundleService,
            )

            scope = PodPromotionScope(
                tenant_schema=(context.tenant_schema or '').strip(),
                driver_id=driver_pk,
                shipment_id=shipment_key,
            )
            bundle_service = PodCaptureBundleService()
            bundle = bundle_service.assert_orphan_bundle_prevented(
                bundle_id,
                scope=scope,
            )
            bundle_media = bundle_service._staging.get_media(bundle.bundle_id)  # noqa: SLF001
        except PodCaptureError as exc:
            raise self._map_pod_capture_error(exc) from exc

        pod_type = str((context.payload or {}).get('pod_type') or '').strip()
        if not pod_type and self._is_digital_pod_execute(context.operation_action):
            pod_type = 'digital'
        requirements = build_pod_capture_requirements(
            context.operation_action,
            pod_capture_type=pod_type,
            shipment=context.shipment,
        )
        context.resolver_meta = dict(context.resolver_meta or {})
        context.resolver_meta['pod_capture_bundle_id'] = bundle.bundle_id
        context.resolver_meta['pod_capture_bundle'] = bundle
        context.resolver_meta['pod_capture_bundle_media'] = list(bundle_media or [])
        context.resolver_meta['pod_capture_compliance'] = requirements

    def _auto_attach_staged_pod_bundle(self, context: ExecuteActionContext) -> str:
        """
        Mobile often POSTs pod/capture then Execute A7 without ``capture_bundle_id``.

        Attach the latest ready staged bundle for this driver+shipment so evidence
        (photo / signature / video) is validated from staging, not an empty body.
        """
        existing = extract_capture_bundle_id(context.payload)
        if existing:
            return existing
        if not self._is_digital_pod_execute(context.operation_action):
            return ''
        if context.job_type != 'shipment':
            return ''
        inline_media = normalize_media_items(list((context.payload or {}).get('media') or []))
        if inline_media:
            return ''
        bundle_id = self._find_latest_ready_pod_bundle_id(context)
        if not bundle_id:
            return ''
        context.payload = dict(context.payload or {})
        context.payload['capture_bundle_id'] = bundle_id
        return bundle_id

    @staticmethod
    def _is_digital_pod_execute(operation_action: Any | None) -> bool:
        if operation_action is None:
            return False
        code = (getattr(operation_action, 'action_code', '') or '').strip().upper()
        if code == 'A7':
            return True
        if bool(getattr(operation_action, 'auto_pod_post', False)):
            return True
        return is_pod_upload_action(operation_action)

    @staticmethod
    def _find_latest_ready_pod_bundle_id(context: ExecuteActionContext) -> str:
        from django.utils import timezone

        from mobile_api.pod_capture.models import PODCaptureBundle

        tenant = (context.tenant_schema or '').strip()
        driver_pk = EvidenceValidationService._driver_pk(context.driver)
        shipment_pk = EvidenceValidationService._shipment_key(context)
        if not (tenant and driver_pk and shipment_pk):
            return ''
        bundle = (
            PODCaptureBundle.objects.filter(
                tenant_schema=tenant,
                shipment_id=shipment_pk,
                driver_id=driver_pk,
                bundle_status=PODCaptureBundle.BundleStatus.READY,
                expires_at__gt=timezone.now(),
            )
            .order_by('-created_at')
            .first()
        )
        if bundle is None:
            return ''
        return str(bundle.pk)

    @staticmethod
    def _driver_pk(driver: Any) -> str:
        if driver is None:
            return ''
        pk = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
        return str(pk or '').strip()

    @staticmethod
    def _shipment_key(context: ExecuteActionContext) -> str:
        shipment = context.shipment
        if shipment is not None:
            return str(
                getattr(shipment, 'pk', None)
                or getattr(shipment, 'shipment_id', None)
                or context.job_id
                or ''
            ).strip()
        return str(context.job_id or '').strip()

    @staticmethod
    def _map_pod_capture_error(exc: Any) -> ExecuteActionError:
        from mobile_api.pod_capture.exceptions import PodCaptureError

        if not isinstance(exc, PodCaptureError):
            raise exc
        body = build_validation_error(
            error_code=exc.code,
            message=str(exc),
            refresh_required=bool(getattr(exc, 'refresh_required', False)),
        )
        return ExecuteActionError(
            str(exc),
            code=exc.code,
            http_status=exc.http_status,
            message_key=exc.message_key,
            refresh_required=bool(getattr(exc, 'refresh_required', False)),
            validation_error=body,
        )

    def _attach_operational_issue_warnings(self, context: ExecuteActionContext) -> None:
        """
        Attach advisory operational issue warnings (no hard-block).

        Execute Action remains workflow authority; warnings surface in ``alerts``.
        """
        from mobile_api.job_detail.projections.job_detail_projection_builder import (
            attach_operational_issue_warnings_to_execute_context,
        )

        attach_operational_issue_warnings_to_execute_context(context)

    def _validate_gps(self, payload: dict[str, Any], requirements: dict[str, Any]) -> None:
        if not requirements.get('gps'):
            return
        latitude = str(payload.get('latitude') or '').strip()
        longitude = str(payload.get('longitude') or '').strip()
        if not latitude or not longitude:
            raise self._evidence_error(
                error_code='gps_required',
                message=str(_('mobile.jobs.execute.gps_required')),
            )

    def _validate_notes(self, payload: dict[str, Any], requirements: dict[str, Any]) -> None:
        requires_note = bool(requirements.get('note'))
        note_required = bool(requirements.get('note_required'))
        if not requires_note and not note_required:
            return
        notes = str(payload.get('notes') or '').strip()
        if not notes:
            raise self._evidence_error(
                error_code='notes_required',
                message=str(_('mobile.jobs.execute.notes_required')),
            )

    def _validate_media(
        self,
        context: ExecuteActionContext,
        requirements: dict[str, Any],
    ) -> None:
        bundle_id = extract_capture_bundle_id(context.payload or {})
        if bundle_id:
            bundle_media = list((context.resolver_meta or {}).get('pod_capture_bundle_media') or [])
            items = [
                SimpleNamespace(
                    media_type=str(getattr(row, 'media_type', '') or ''),
                    file_ref=str(getattr(row, 'file_ref', '') or ''),
                    upload=None,
                    media_id='',
                )
                for row in bundle_media
            ]
        else:
            items = normalize_media_items(list((context.payload or {}).get('media') or []))
        photo_min = int(requirements.get('photo_min_count') or 0)
        video_min = int(requirements.get('video_min_count') or 0)
        requires_photo = bool(requirements.get('photo')) or photo_min > 0
        requires_video = bool(requirements.get('video')) or video_min > 0
        requires_signature = bool(requirements.get('signature'))

        if not items and not (requires_photo or requires_video or requires_signature):
            return

        if len(items) > EXECUTION_MEDIA_MAX_ITEMS:
            raise self._evidence_error(
                error_code='media_limit_exceeded',
                message=str(_('mobile.jobs.execute.media_limit_exceeded')),
            )

        photo_count = 0
        video_count = 0
        document_count = 0
        signature_count = 0

        for item in items:
            media_type = (item.media_type or '').strip().casefold()
            if media_type and media_type not in ALLOWED_MEDIA_TYPES:
                raise self._evidence_error(
                    error_code='invalid_media_type',
                    message=str(_('mobile.jobs.execute.invalid_media_type')),
                )

            if requires_photo or requires_video or requires_signature:
                if not item.file_ref and not item.upload and not item.media_id:
                    raise self._evidence_error(
                        error_code='media_file_required',
                        message=str(_('mobile.jobs.execute.media_file_required')),
                    )

            if media_type == 'signature':
                signature_count += 1
            if media_type in PHOTO_MEDIA_TYPES:
                photo_count += 1
            elif media_type in VIDEO_MEDIA_TYPES:
                video_count += 1
            elif media_type == 'document':
                document_count += 1

        if photo_count > EXECUTION_MEDIA_MAX_PHOTOS:
            raise self._evidence_error(
                error_code='photo_limit_exceeded',
                message=str(_('mobile.jobs.execute.photo_limit_exceeded')),
            )
        video_max = int(requirements.get('video_max_count') or 0)
        if video_max <= 0:
            video_max = EXECUTION_MEDIA_MAX_VIDEOS
        if video_count > video_max:
            raise self._evidence_error(
                error_code='video_limit_exceeded',
                message=str(_('mobile.jobs.execute.video_limit_exceeded')),
            )
        if document_count > EXECUTION_MEDIA_MAX_DOCUMENTS:
            raise self._evidence_error(
                error_code='document_limit_exceeded',
                message=str(_('mobile.jobs.execute.document_limit_exceeded')),
            )

        if requires_photo and photo_count < photo_min:
            raise self._evidence_error(
                error_code='photo_required',
                message=str(_('mobile.jobs.execute.photo_required')),
            )
        if requires_video and video_count < video_min:
            raise self._evidence_error(
                error_code='video_required',
                message=str(_('mobile.jobs.execute.video_required')),
            )
        if requires_signature and signature_count < 1:
            raise self._evidence_error(
                error_code='signature_required',
                message=str(_('mobile.jobs.execute.signature_required')),
            )

        if requires_video and video_count > 0:
            for item in items:
                mtype = (item.media_type or '').strip().casefold()
                if mtype and mtype not in VIDEO_MEDIA_TYPES | PHOTO_MEDIA_TYPES | {'document'}:
                    raise self._evidence_error(
                        error_code='invalid_media_type',
                        message=str(_('mobile.jobs.execute.invalid_media_type')),
                    )

    @staticmethod
    def _evidence_error(
        *,
        error_code: str,
        message: str,
        http_status: int = 400,
    ) -> ExecuteActionError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=False,
        )
        return ExecuteActionError(
            message,
            code=error_code,
            http_status=http_status,
            message_key=f'mobile.jobs.execute.{error_code}',
            refresh_required=False,
            validation_error=body,
        )
