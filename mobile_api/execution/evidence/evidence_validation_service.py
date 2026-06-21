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
from mobile_api.execution.messages import execute_user_message
from mobile_api.helpers.action_execution_metadata import build_execution_requirements
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_pod_upload_action,
)
from mobile_api.utils.file_upload_handler import infer_media_type


def _inline_media_blocks_bundle_attach(payload: dict[str, Any] | None) -> bool:
    """
  Only treat inline ``media[]`` as authoritative when rows carry real file refs.

  Mobile often sends placeholder ``media`` rows on Execute A7 while evidence
  lives in a staged ``PODCaptureBundle`` from ``POST .../pod/capture/``.
  """
    items = normalize_media_items(list((payload or {}).get('media') or []))
    return any(
        (item.file_ref or '').strip() or item.upload or (item.media_id or '').strip()
        for item in items
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
            merged_media = list(
                (context.resolver_meta or {}).get('pod_capture_merged_bundle_media') or []
            )
            if merged_media:
                bundle_media = EvidenceValidationService._normalize_bundle_media_rows(
                    merged_media,
                )
            else:
                bundle_media = EvidenceValidationService._normalize_bundle_media_rows(
                    bundle_service._staging.get_media(bundle.bundle_id),  # noqa: SLF001
                )
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
        merged = list(
            (context.resolver_meta or {}).get('pod_capture_merged_bundle_media') or []
        )
        if _inline_media_blocks_bundle_attach(context.payload) and not merged:
            if not self._inline_media_missing_staged_evidence(context):
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
        if not (tenant and driver_pk):
            return ''

        shipment_keys: list[str] = []
        for candidate in (
            EvidenceValidationService._shipment_key(context),
            str(context.job_id or '').strip(),
            str(getattr(context.shipment, 'pk', '') or '').strip(),
            str(getattr(context.shipment, 'shipment_id', '') or '').strip(),
            str(getattr(context.shipment, 'shipment_no', '') or '').strip(),
        ):
            if candidate and candidate not in shipment_keys:
                shipment_keys.append(candidate)
        if not shipment_keys:
            return ''

        base_qs = PODCaptureBundle.objects.filter(
            tenant_schema=tenant,
            driver_id=driver_pk,
            bundle_status=PODCaptureBundle.BundleStatus.READY,
            expires_at__gt=timezone.now(),
        ).order_by('-created_at')

        for shipment_id in shipment_keys:
            bundle = base_qs.filter(shipment_id=shipment_id).first()
            if bundle is not None:
                return str(bundle.pk)
        return ''

    @staticmethod
    def _normalize_bundle_media_rows(rows: list[Any] | None) -> list[Any]:
        """Correct mislabeled staged media (photo → video) before A7 validation."""
        normalized: list[Any] = []
        for row in list(rows or []):
            resolved = EvidenceValidationService._resolve_row_media_type(row)
            if isinstance(row, dict):
                row = dict(row)
                row['media_type'] = resolved
            else:
                current = str(getattr(row, 'media_type', '') or '').strip().casefold()
                if resolved != current and hasattr(row, 'media_type'):
                    row.media_type = resolved
            normalized.append(row)
        return normalized

    @staticmethod
    def _row_file_ref(row: Any) -> str:
        if isinstance(row, dict):
            return str(row.get('file_ref') or '').strip()
        return str(getattr(row, 'file_ref', '') or '').strip()

    @staticmethod
    def _resolve_row_media_type(row: Any) -> str:
        if isinstance(row, dict):
            duration_seconds = row.get('duration_seconds')
            return infer_media_type(
                explicit=str(row.get('media_type') or ''),
                content_type=str(row.get('mime_type') or ''),
                file_ref=str(row.get('file_ref') or ''),
                file_name=str(row.get('file_name') or ''),
                duration_seconds=duration_seconds,
            )
        duration_seconds = getattr(row, 'duration_seconds', None)
        return infer_media_type(
            explicit=str(getattr(row, 'media_type', '') or ''),
            content_type=str(getattr(row, 'mime_type', '') or ''),
            file_ref=str(getattr(row, 'file_ref', '') or ''),
            file_name=str(getattr(row, 'file_name', '') or ''),
            duration_seconds=duration_seconds,
        )

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
        if not bool(requirements.get('note_required')):
            return
        notes = str(payload.get('notes') or '').strip()
        if not notes:
            message_key = 'mobile.jobs.execute.notes_required'
            raise self._evidence_error(
                error_code='notes_required',
                message=execute_user_message(message_key),
                message_key=message_key,
                field='notes',
            )

    @staticmethod
    def _evidence_row_as_dict(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return dict(row)
        return {
            'media_type': str(getattr(row, 'media_type', '') or ''),
            'file_ref': str(getattr(row, 'file_ref', '') or '').strip(),
            'file_name': str(getattr(row, 'file_name', '') or ''),
            'mime_type': str(getattr(row, 'mime_type', '') or ''),
            'line_no': int(getattr(row, 'line_no', None) or 0),
            'duration_seconds': getattr(row, 'duration_seconds', None),
        }

    @staticmethod
    def _collect_evidence_media_items(context: ExecuteActionContext) -> list[Any]:
        """Merge staged POD rows with inline execute media for validation."""
        from mobile_api.execution.services.a7_pod_evidence_resolver import (
            _merge_media_dicts,
        )

        resolver_meta = context.resolver_meta or {}
        merged_rows = resolver_meta.get('pod_capture_merged_bundle_media')
        if merged_rows:
            staged_rows = [
                EvidenceValidationService._evidence_row_as_dict(row)
                for row in merged_rows
            ]
        else:
            staged_rows = [
                EvidenceValidationService._evidence_row_as_dict(row)
                for row in list(resolver_meta.get('pod_capture_bundle_media') or [])
            ]
        inline_rows = []
        for item in normalize_media_items(
            list((context.payload or {}).get('media') or [])
        ):
            file_ref = (item.file_ref or '').strip()
            if not file_ref and not item.upload and not (item.media_id or '').strip():
                continue
            inline_rows.append(
                {
                    'media_type': item.media_type,
                    'file_ref': file_ref,
                    'file_name': item.file_name,
                    'line_no': item.line_no,
                    'duration_seconds': item.duration_seconds,
                }
            )
        merged_rows = _merge_media_dicts(staged_rows, inline_rows)
        if merged_rows:
            return [
                SimpleNamespace(
                    media_type=EvidenceValidationService._resolve_row_media_type(row),
                    file_ref=EvidenceValidationService._row_file_ref(row),
                    upload=None,
                    media_id='',
                    duration_seconds=row.get('duration_seconds')
                    if isinstance(row, dict)
                    else getattr(row, 'duration_seconds', None),
                )
                for row in merged_rows
            ]
        return normalize_media_items(list((context.payload or {}).get('media') or []))

    @staticmethod
    def _inline_media_missing_staged_evidence(context: ExecuteActionContext) -> bool:
        """True when inline execute media lacks video/signature that staging may hold."""
        from mobile_api.execution.evidence.constants import VIDEO_MEDIA_TYPES

        operation_action = context.operation_action
        if operation_action is None:
            return False
        try:
            from mobile_api.pod_capture.policy.pod_capture_policy import (
                build_pod_capture_requirements,
            )

            requirements = build_pod_capture_requirements(
                operation_action,
                pod_capture_type='digital',
                shipment=context.shipment,
            )
        except Exception:
            return True

        items = normalize_media_items(list((context.payload or {}).get('media') or []))
        video_min = int(requirements.get('video_min_count') or 0)
        requires_video = bool(requirements.get('video')) or video_min > 0
        requires_signature = bool(requirements.get('signature'))
        video_count = sum(
            1 for item in items if (item.media_type or '') in VIDEO_MEDIA_TYPES
        )
        signature_count = sum(
            1 for item in items if (item.media_type or '').casefold() == 'signature'
        )
        if requires_video and video_count < max(video_min, 1):
            return True
        if requires_signature and signature_count < 1:
            return True
        return False

    def _validate_media(
        self,
        context: ExecuteActionContext,
        requirements: dict[str, Any],
    ) -> None:
        from mobile_api.execution.evidence.pod_evidence_consolidation import (
            consolidate_pod_evidence_items,
        )

        items = consolidate_pod_evidence_items(
            self._collect_evidence_media_items(context),
            requirements,
        )
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
            elif media_type == 'photo':
                photo_count += 1
            elif media_type in VIDEO_MEDIA_TYPES:
                video_count += 1
            elif media_type == 'document':
                document_count += 1

        photo_max = int(requirements.get('photo_max_count') or 0) or EXECUTION_MEDIA_MAX_PHOTOS
        if photo_count > photo_max:
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

        self._validate_video_duration(items, requirements)

    def _validate_video_duration(
        self,
        items: list[Any],
        requirements: dict[str, Any],
    ) -> None:
        from mobile_api.execution.evidence.constants import (
            POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
        )
        from mobile_api.execution.evidence.video_duration_validation import (
            is_video_duration_exceeded,
            video_duration_exceeded_message,
        )

        requires_video = bool(requirements.get('video')) or int(
            requirements.get('video_min_count') or 0
        ) > 0
        max_duration_raw = requirements.get('video_max_duration_seconds')
        if max_duration_raw is None and not requires_video:
            return
        max_duration = int(max_duration_raw or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS)
        if max_duration <= 0:
            return
        for item in items:
            duration = getattr(item, 'duration_seconds', None)
            if is_video_duration_exceeded(
                media_type=getattr(item, 'media_type', '') or '',
                duration_seconds=duration,
                max_duration_seconds=max_duration,
            ):
                raise self._evidence_error(
                    error_code='video_duration_exceeded',
                    message=video_duration_exceeded_message(
                        max_duration_seconds=max_duration,
                    ),
                )

    @staticmethod
    def _evidence_error(
        *,
        error_code: str,
        message: str,
        http_status: int = 400,
        message_key: str = '',
        field: str = '',
    ) -> ExecuteActionError:
        key = (message_key or f'mobile.jobs.execute.{error_code}').strip()
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=False,
            field=field,
        )
        return ExecuteActionError(
            message,
            code=error_code,
            http_status=http_status,
            message_key=key,
            refresh_required=False,
            validation_error=body,
        )
