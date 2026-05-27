"""
mobile_api/pod_capture/policy/pod_evidence_immutability_policy.py

Legal/audit immutability rules for POD evidence after Action Log promotion.

POD bundles are **append-only** evidence chains:

* Staged media rows are never replaced in-place after promotion.
* Action Log media persistence must **not** delete sibling rows (``replace_existing=False``).
* Promoted bundles and file refs cannot be re-staged or mutated via POD Capture.
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.evidence.action_log_media_persistence import (
    ActionLogMediaItem,
    persist_action_log_media_rows,
)

# POD promotion must never use portal "replace all media" semantics.
POD_EVIDENCE_REPLACE_EXISTING: bool = False


def assert_bundle_mutable_for_staging(bundle: Any) -> None:
    """Reject any capture mutation once bundle reached promoted terminal state."""
    if bundle is None:
        return
    if getattr(bundle, 'is_promoted', lambda: False)():
        from mobile_api.pod_capture.exceptions import PodCaptureError
        from django.utils.translation import gettext_lazy as _

        raise PodCaptureError(
            str(_('mobile.pod_capture.bundle_immutable')),
            code='bundle_immutable',
            http_status=409,
            message_key='mobile.pod_capture.bundle_immutable',
        )
    status = getattr(bundle, 'status', None)
    promoted_value = getattr(status, 'value', status)
    if promoted_value == 'promoted':
        from mobile_api.pod_capture.exceptions import PodCaptureError
        from django.utils.translation import gettext_lazy as _

        raise PodCaptureError(
            str(_('mobile.pod_capture.bundle_immutable')),
            code='bundle_immutable',
            http_status=409,
            message_key='mobile.pod_capture.bundle_immutable',
        )


def persist_pod_action_log_media(
    action_log: Any,
    items: list[ActionLogMediaItem],
) -> list[Any]:
    """
    Append-only Action Log media persistence for POD promotion.

    Always uses ``replace_existing=False`` — never deletes prior evidence rows.
    """
    return persist_action_log_media_rows(
        action_log,
        items,
        replace_existing=POD_EVIDENCE_REPLACE_EXISTING,
        immutable=True,
    )
