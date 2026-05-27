"""
mobile_api/pod_capture/guards/immutable_evidence_guard.py

Enforce append-only policy for promoted POD evidence (no overwrite / replace).
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.settings import pod_capture_enforce_immutability

logger = logging.getLogger('mobile_api.pod_capture.security')


class ImmutableEvidenceGuard:
    """Block mutation of promoted POD media and log security audit events."""

    def assert_replace_allowed(
        self,
        *,
        replace_existing: bool,
        immutable: bool,
        media_id: str = '',
        action_log_id: str = '',
    ) -> None:
        if not pod_capture_enforce_immutability():
            return
        if not replace_existing:
            return
        if not immutable:
            return
        self._reject(
            code='pod_evidence_immutable',
            media_id=media_id,
            action_log_id=action_log_id,
            reason='replace_existing_blocked',
        )

    def assert_media_mutable(self, *, promoted: bool, immutable: bool) -> None:
        if not pod_capture_enforce_immutability():
            return
        if promoted or immutable:
            self._reject(code='pod_media_immutable', reason='mutation_blocked')

    def assert_file_ref_not_reused(self, *, promoted: bool, file_ref: str) -> None:
        if not pod_capture_enforce_immutability():
            return
        if promoted and (file_ref or '').strip():
            self._reject(code='pod_file_ref_immutable', reason='file_ref_reuse_blocked')

    def _reject(
        self,
        *,
        code: str,
        reason: str,
        media_id: str = '',
        action_log_id: str = '',
    ) -> None:
        logger.warning(
            'pod_immutable_violation code=%s reason=%s media_id=%s action_log_id=%s',
            code,
            reason,
            media_id,
            action_log_id,
        )
        raise PodCaptureError(
            str(_('mobile.pod_capture.evidence_immutable')),
            code=code,
            http_status=409,
            message_key='mobile.pod_capture.evidence_immutable',
        )


def guard_persist_kwargs(**kwargs: Any) -> None:
    """Entry for Action Log media persistence — POD promotion path sets immutable=True."""
    ImmutableEvidenceGuard().assert_replace_allowed(
        replace_existing=bool(kwargs.get('replace_existing')),
        immutable=bool(kwargs.get('immutable')),
        media_id=str(kwargs.get('media_id') or ''),
        action_log_id=str(kwargs.get('action_log_id') or ''),
    )
