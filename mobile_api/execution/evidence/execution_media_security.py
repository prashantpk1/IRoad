"""
mobile_api/execution/evidence/execution_media_security.py

Enterprise media ingestion policy for mobile execute ``media[]``.
"""
from __future__ import annotations

import mimetypes
import os
import re
from pathlib import PurePosixPath
from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execution_validation_error import build_validation_error
from mobile_api.execution.evidence.action_log_media_persistence import (
    ActionLogMediaItem,
    normalize_media_items,
)
from mobile_api.execution.evidence.constants import (
    ALLOWED_MEDIA_TYPES,
    FILE_REF_MAX_LENGTH,
    PHOTO_MEDIA_TYPES,
    VIDEO_MEDIA_TYPES,
)
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.settings import mobile_execution_verify_media_storage

_ALLOWED_PREFIXES = (
    'tenant_operation_action_media/',
    'mobile_driver_uploads/',
    'tenant-uploads/',
    # Direct multipart uploads from execute / ops endpoints
    # (see mobile_api.utils.file_upload_handler.save_uploaded_file).
    'mobile/',
)

_EXTENSION_BY_MEDIA: dict[str, frozenset[str]] = {
    'photo': frozenset({'.jpg', '.jpeg', '.png', '.webp', '.heic'}),
    'signature': frozenset({'.jpg', '.jpeg', '.png', '.webp'}),
    'video': frozenset({'.mp4', '.mov', '.webm'}),
    'document': frozenset({'.pdf', '.jpg', '.jpeg', '.png'}),
}

_MIME_BY_MEDIA: dict[str, frozenset[str]] = {
    'photo': frozenset({'image/jpeg', 'image/png', 'image/webp', 'image/heic'}),
    'signature': frozenset({'image/jpeg', 'image/png', 'image/webp'}),
    'video': frozenset({'video/mp4', 'video/quicktime', 'video/webm'}),
    'document': frozenset({'application/pdf', 'image/jpeg', 'image/png'}),
}

_MAX_BYTES_DEFAULT = 25 * 1024 * 1024


class ExecutionMediaSecurityService:
    """Validate media attachments before Action Log media persistence."""

    def validate_media(self, context: ExecuteActionContext) -> list[ActionLogMediaItem]:
        if context.idempotent_replay:
            return []
        items = normalize_media_items(list((context.payload or {}).get('media') or []))
        if not items:
            return items

        driver_pk = self._driver_pk(context.driver)
        for item in items:
            self._validate_item(context, item, driver_pk=driver_pk)
        return items

    def _validate_item(
        self,
        context: ExecuteActionContext,
        item: ActionLogMediaItem,
        *,
        driver_pk: str,
    ) -> None:
        media_type = (item.media_type or '').strip().casefold()
        if media_type and media_type not in ALLOWED_MEDIA_TYPES:
            raise self._security_error(
                'invalid_media_type',
                str(_('mobile.jobs.execute.invalid_media_type')),
            )

        if item.upload is not None:
            self._validate_upload(item, media_type=media_type)
            return

        if item.media_id:
            self._validate_media_id(context, item.media_id, driver_pk=driver_pk)
            return

        file_ref = (item.file_ref or '').strip()
        if not file_ref:
            raise self._security_error(
                'media_file_required',
                str(_('mobile.jobs.execute.media_file_required')),
            )

        self._validate_file_ref_path(file_ref, media_type=media_type, driver_pk=driver_pk)

    def _validate_file_ref_path(
        self,
        file_ref: str,
        *,
        media_type: str,
        driver_pk: str,
    ) -> None:
        if len(file_ref) > FILE_REF_MAX_LENGTH:
            raise self._security_error(
                'media_path_too_long',
                str(_('mobile.jobs.execute.media_path_too_long')),
            )

        normalized = file_ref.replace('\\', '/').lstrip('/')
        if '..' in normalized.split('/'):
            raise self._security_error(
                'media_path_traversal',
                str(_('mobile.jobs.execute.media_path_traversal')),
            )

        if not any(normalized.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
            raise self._security_error(
                'media_path_not_allowed',
                str(_('mobile.jobs.execute.media_path_not_allowed')),
            )

        if driver_pk and normalized.startswith('mobile_driver_uploads/'):
            expected = f'mobile_driver_uploads/{driver_pk}/'
            if not normalized.startswith(expected):
                raise self._security_error(
                    'media_driver_mismatch',
                    str(_('mobile.jobs.execute.media_driver_mismatch')),
                )

        ext = PurePosixPath(normalized).suffix.lower()
        allowed_ext = _EXTENSION_BY_MEDIA.get(media_type) or frozenset()
        if allowed_ext and ext and ext not in allowed_ext:
            raise self._security_error(
                'media_extension_not_allowed',
                str(_('mobile.jobs.execute.media_extension_not_allowed')),
            )

        guessed_mime = mimetypes.guess_type(normalized)[0] or ''
        allowed_mimes = _MIME_BY_MEDIA.get(media_type)
        if allowed_mimes and guessed_mime and guessed_mime not in allowed_mimes:
            raise self._security_error(
                'media_mime_not_allowed',
                str(_('mobile.jobs.execute.media_mime_not_allowed')),
            )

        if mobile_execution_verify_media_storage():
            self._assert_storage_object(normalized)

    def _assert_storage_object(self, storage_path: str) -> None:
        from django.conf import settings
        from django.core.files.storage import default_storage

        if not default_storage.exists(storage_path):
            raise self._security_error(
                'media_storage_not_found',
                str(_('mobile.jobs.execute.media_storage_not_found')),
            )

        max_bytes = int(
            getattr(settings, 'MOBILE_EXECUTION_MEDIA_MAX_BYTES', _MAX_BYTES_DEFAULT)
        )
        try:
            size = default_storage.size(storage_path)
        except Exception:
            size = None
        if size is not None and size > max_bytes:
            raise self._security_error(
                'media_file_too_large',
                str(_('mobile.jobs.execute.media_file_too_large')),
            )

    @staticmethod
    def _validate_upload(item: ActionLogMediaItem, *, media_type: str) -> None:
        upload = item.upload
        name = str(getattr(upload, 'name', '') or '')
        ext = os.path.splitext(name)[1].lower()
        allowed_ext = _EXTENSION_BY_MEDIA.get(media_type) or frozenset()
        if allowed_ext and ext and ext not in allowed_ext:
            raise ExecutionMediaSecurityService._security_error(
                'media_extension_not_allowed',
                str(_('mobile.jobs.execute.media_extension_not_allowed')),
            )
        content_type = str(getattr(upload, 'content_type', '') or '').strip().lower()
        allowed_mimes = _MIME_BY_MEDIA.get(media_type)
        if allowed_mimes and content_type and content_type not in allowed_mimes:
            raise ExecutionMediaSecurityService._security_error(
                'media_mime_not_allowed',
                str(_('mobile.jobs.execute.media_mime_not_allowed')),
            )
        try:
            size = int(getattr(upload, 'size', 0) or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            raise ExecutionMediaSecurityService._security_error(
                'media_file_required',
                str(_('mobile.jobs.execute.media_file_required')),
            )

    def _validate_media_id(
        self,
        context: ExecuteActionContext,
        media_id: str,
        *,
        driver_pk: str,
    ) -> None:
        from tenant_workspace.models import TenantOperationActionMedia

        token = (media_id or '').strip()
        if not token:
            return
        row = TenantOperationActionMedia.objects.filter(media_id=token).first()
        if row is None:
            raise self._security_error(
                'media_not_found',
                str(_('mobile.jobs.execute.media_not_found')),
            )
        file_name = str(getattr(row.file, 'name', '') or '').strip()
        if file_name:
            self._validate_file_ref_path(
                file_name,
                media_type=(row.media_type or '').casefold(),
                driver_pk=driver_pk,
            )

    @staticmethod
    def _driver_pk(driver: Any) -> str:
        if driver is None:
            return ''
        pk = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
        return str(pk or '').strip()

    @staticmethod
    def _security_error(error_code: str, message: str) -> ExecuteActionError:
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
