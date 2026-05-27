"""
mobile_api/pod_capture/guards/pod_capture_security_guard.py

POD-specific media path policy — tenant + driver + shipment scoped staging paths.

Path contract::

    mobile_driver_uploads/{tenant_schema}/{driver_id}/{shipment_id}/pod_capture/...

Rejects:

* orphan uploads (path outside scope or unregistered cross-bundle reuse)
* cross-tenant / cross-driver / cross-shipment paths
* already-promoted file refs
"""
from __future__ import annotations

import mimetypes
import os
from pathlib import PurePosixPath

from django.utils.translation import gettext_lazy as _

from mobile_api.execution.evidence.constants import ALLOWED_MEDIA_TYPES
from mobile_api.execution.evidence.execution_media_security import (
    ExecutionMediaSecurityService,
    _EXTENSION_BY_MEDIA,
    _MIME_BY_MEDIA,
)
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput, StagingScope
from mobile_api.pod_capture.dto.validation_error import build_validation_error
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.settings import pod_capture_verify_media_storage
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


class PodCaptureSecurityGuard:
    """Validate staged media paths and staging registry before bundle persistence."""

    def __init__(self, *, staging: EvidenceStagingService | None = None) -> None:
        self._staging = staging or EvidenceStagingService()

    def validate_media_items(self, context: PodCaptureContext) -> list[PODCaptureMediaItemInput]:
        if context.idempotent_replay:
            return list(context.media_items or [])

        items = list(context.media_items or [])
        if not items:
            return items

        scope = self._staging.scope_from_context(context)
        bundle_id = getattr(context.bundle, 'bundle_id', None) if context.bundle else None

        for item in items:
            self._validate_item(
                item,
                scope=scope,
                bundle_id=bundle_id,
            )
        return items

    def _validate_item(
        self,
        item: PODCaptureMediaItemInput,
        *,
        scope: StagingScope,
        bundle_id: str | None,
    ) -> None:
        media_type = (item.media_type or '').strip().casefold()
        if media_type and media_type not in ALLOWED_MEDIA_TYPES:
            raise self._security_error(
                'invalid_media_type',
                str(_('mobile.pod_capture.invalid_media_type')),
            )

        if item.upload is not None:
            self._validate_upload(item, media_type=media_type, scope=scope)
            return

        file_ref = (item.file_ref or '').strip()
        if not file_ref:
            raise self._security_error(
                'media_file_required',
                str(_('mobile.pod_capture.media_file_required')),
            )

        self._validate_file_ref_path(
            file_ref,
            media_type=media_type,
            scope=scope,
            bundle_id=bundle_id,
        )

    def _validate_file_ref_path(
        self,
        file_ref: str,
        *,
        media_type: str,
        scope: StagingScope,
        bundle_id: str | None,
    ) -> None:
        normalized = file_ref.replace('\\', '/').lstrip('/')
        if '..' in normalized.split('/'):
            raise self._security_error(
                'media_path_traversal',
                str(_('mobile.pod_capture.media_path_traversal')),
            )

        if len(normalized) > 500:
            raise self._security_error(
                'media_path_too_long',
                str(_('mobile.pod_capture.media_path_too_long')),
            )

        self._staging.assert_file_ref_uploadable(
            normalized,
            scope=scope,
            bundle_id=bundle_id,
        )

        ext = PurePosixPath(normalized).suffix.lower()
        allowed_ext = _EXTENSION_BY_MEDIA.get(media_type) or frozenset()
        if allowed_ext and ext and ext not in allowed_ext:
            raise self._security_error(
                'media_extension_not_allowed',
                str(_('mobile.pod_capture.media_extension_not_allowed')),
            )

        guessed_mime = mimetypes.guess_type(normalized)[0] or ''
        allowed_mimes = _MIME_BY_MEDIA.get(media_type)
        if allowed_mimes and guessed_mime and guessed_mime not in allowed_mimes:
            raise self._security_error(
                'media_mime_not_allowed',
                str(_('mobile.pod_capture.media_mime_not_allowed')),
            )

        if pod_capture_verify_media_storage():
            try:
                ExecutionMediaSecurityService._assert_storage_object(  # noqa: SLF001
                    ExecutionMediaSecurityService,
                    normalized,
                )
            except Exception as exc:
                from mobile_api.execution.exceptions import ExecuteActionError
                from mobile_api.pod_capture.services.pod_evidence_adapter import (
                    map_execute_error,
                )

                if isinstance(exc, ExecuteActionError):
                    raise map_execute_error(exc) from exc
                raise

    @staticmethod
    def build_expected_upload_prefix(
        *,
        tenant_schema: str,
        driver_pk: str,
        shipment_pk: str,
    ) -> str:
        return StagingScope(
            tenant_schema=tenant_schema,
            driver_id=driver_pk,
            shipment_id=shipment_pk,
            client_capture_id='',
        ).storage_prefix()

    @staticmethod
    def _validate_upload(
        item: PODCaptureMediaItemInput,
        *,
        media_type: str,
        scope: StagingScope,
    ) -> None:
        upload = item.upload
        name = str(getattr(upload, 'name', '') or '')
        ext = os.path.splitext(name)[1].lower()
        allowed_ext = _EXTENSION_BY_MEDIA.get(media_type) or frozenset()
        if allowed_ext and ext and ext not in allowed_ext:
            raise PodCaptureSecurityGuard._security_error(
                'media_extension_not_allowed',
                str(_('mobile.pod_capture.media_extension_not_allowed')),
            )
        content_type = str(getattr(upload, 'content_type', '') or '').strip().lower()
        allowed_mimes = _MIME_BY_MEDIA.get(media_type)
        if allowed_mimes and content_type and content_type not in allowed_mimes:
            raise PodCaptureSecurityGuard._security_error(
                'media_mime_not_allowed',
                str(_('mobile.pod_capture.media_mime_not_allowed')),
            )
        try:
            size = int(getattr(upload, 'size', 0) or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            raise PodCaptureSecurityGuard._security_error(
                'media_file_required',
                str(_('mobile.pod_capture.media_file_required')),
            )

        if name:
            PodCaptureSecurityGuard._validate_file_ref_path_static(
                name,
                media_type=media_type,
                scope=scope,
            )

    @staticmethod
    def _validate_file_ref_path_static(
        file_ref: str,
        *,
        media_type: str,
        scope: StagingScope,
    ) -> None:
        normalized = file_ref.replace('\\', '/').lstrip('/')
        if not normalized.startswith(scope.storage_prefix()):
            raise PodCaptureSecurityGuard._security_error(
                'orphan_upload',
                str(_('mobile.pod_capture.orphan_upload')),
            )

    @staticmethod
    def _security_error(error_code: str, message: str) -> PodCaptureError:
        body = build_validation_error(
            error_code=error_code,
            message=message,
            refresh_required=False,
        )
        return PodCaptureError(
            message,
            code=error_code,
            http_status=400,
            message_key=f'mobile.pod_capture.{error_code}',
            refresh_required=False,
            validation_error=body,
        )
