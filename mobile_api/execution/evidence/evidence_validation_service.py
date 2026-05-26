"""
mobile_api/execution/evidence/evidence_validation_service.py

Server-side enforcement of GPS / media / note requirements from Action Master metadata.
"""
from __future__ import annotations

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

        requirements = build_execution_requirements(operation_action)
        payload = context.payload or {}

        self._validate_gps(payload, requirements)
        self._validate_notes(payload, requirements)
        self._media_security.validate_media(context)
        self._validate_media(context, requirements)

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
        if video_count > EXECUTION_MEDIA_MAX_VIDEOS:
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
    def _evidence_error(*, error_code: str, message: str) -> ExecuteActionError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=False,
        )
        return ExecuteActionError(
            message,
            code=error_code,
            http_status=400,
            message_key=f'mobile.jobs.execute.{error_code}',
            refresh_required=False,
            validation_error=body,
        )
