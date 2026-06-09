"""
mobile_api/pod_capture/policy/pod_capture_policy.py

POD-type overlays on Action Master ``build_execution_requirements``.

Rules are derived from:

* ``build_execution_requirements(operation_action)`` (execution metadata)
* ``pod_capture_type`` client hint (digital / soft / hard / …)
* Shipment column hints (``pod_type``, ``pod_doc_count``)
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.evidence.constants import (
    POD_CAPTURE_VIDEO_MAX_COUNT,
    POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
    POD_CAPTURE_VIDEO_MIN_COUNT,
)
from mobile_api.helpers.action_execution_metadata import build_execution_requirements
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_hard_pod_action,
    is_pod_upload_action,
)

POD_CAPTURE_TYPES = frozenset(
    {
        'digital',
        'soft',
        'hard',
        'signature',
        'video',
        'multi_page',
    }
)


def merge_execution_requirements(
    base: dict[str, Any],
    overlay: dict[str, Any],
) -> dict[str, Any]:
    """Merge overlay onto base using max for counts and OR for boolean flags."""
    merged = dict(base or {})
    overlay = overlay or {}
    for key in (
        'gps',
        'photo',
        'video',
        'video_optional',
        'note',
        'note_required',
        'signature',
        'auto_pod_post',
        'hard_copy_collection',
    ):
        if key in overlay:
            merged[key] = bool(merged.get(key)) or bool(overlay.get(key))

    for key in ('photo_min_count', 'video_min_count', 'document_min_count'):
        merged[key] = max(int(merged.get(key) or 0), int(overlay.get(key) or 0))

    for key in ('video_max_count',):
        base_val = int(merged.get(key) or 0)
        overlay_val = int(overlay.get(key) or 0)
        if overlay_val <= 0:
            continue
        if base_val <= 0:
            merged[key] = overlay_val
        else:
            merged[key] = min(base_val, overlay_val)

    return merged


def derive_pod_type_overlay(
    pod_capture_type: str | None,
    *,
    operation_action: Any | None = None,
    shipment: Any | None = None,
) -> dict[str, Any]:
    """
    Type-specific evidence expectations for POD Capture (not generic upload).

    Does not hardcode tenant workflows — uses capture type + action/shipment hints.
    """
    token = (pod_capture_type or '').strip().casefold()
    if token and token not in POD_CAPTURE_TYPES:
        return {}

    overlay: dict[str, Any] = {}

    if not token and operation_action is not None:
        if is_hard_pod_action(operation_action):
            token = 'hard'
        elif is_pod_upload_action(operation_action):
            token = 'digital'
            if shipment is not None:
                shipment_pod = (
                    getattr(shipment, 'pod_type', None) or ''
                ).strip().casefold()
                if shipment_pod == 'hard':
                    token = 'hard'

    if token == 'digital':
        overlay['photo'] = True
        overlay['photo_min_count'] = max(int(overlay.get('photo_min_count') or 0), 1)
        # IRoute §14.5.1 — digital POD: photo + signature + one video clip (max 15s).
        overlay['video'] = True
        overlay['video_min_count'] = max(
            int(overlay.get('video_min_count') or 0),
            POD_CAPTURE_VIDEO_MIN_COUNT,
        )
        overlay['video_max_count'] = max(
            int(overlay.get('video_max_count') or 0),
            POD_CAPTURE_VIDEO_MAX_COUNT,
        )
        overlay['video_optional'] = False
        overlay['video_max_duration_seconds'] = POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    elif token == 'soft':
        overlay['photo'] = True
        overlay['photo_min_count'] = max(int(overlay.get('photo_min_count') or 0), 1)
    elif token == 'hard':
        overlay['photo'] = True
        overlay['hard_copy_collection'] = True
        overlay['photo_min_count'] = max(int(overlay.get('photo_min_count') or 0), 1)
    elif token == 'signature':
        overlay['signature'] = True
        overlay['photo_min_count'] = max(int(overlay.get('photo_min_count') or 0), 0)
    elif token == 'video':
        overlay['video'] = True
        overlay['video_min_count'] = max(int(overlay.get('video_min_count') or 0), 1)
    elif token == 'multi_page':
        page_count = int(getattr(shipment, 'pod_doc_count', None) or 0)
        doc_min = max(page_count, 1)
        overlay['document_min_count'] = doc_min
        overlay['photo_min_count'] = max(int(overlay.get('photo_min_count') or 0), 1)

    return overlay


def build_pod_capture_requirements(
    operation_action: Any | None,
    *,
    pod_capture_type: str = '',
    shipment: Any | None = None,
) -> dict[str, Any]:
    """Full compliance requirement dict for one capture request."""
    base = build_execution_requirements(operation_action) if operation_action else {}
    overlay = derive_pod_type_overlay(
        pod_capture_type,
        operation_action=operation_action,
        shipment=shipment,
    )
    merged = merge_execution_requirements(base, overlay)

    if is_pod_upload_action(operation_action):
        merged['signature'] = bool(merged.get('signature')) or bool(
            base.get('signature')
        )
    if is_hard_pod_action(operation_action) or merged.get('hard_copy_collection'):
        merged['photo'] = True
        merged['photo_min_count'] = max(int(merged.get('photo_min_count') or 0), 1)

    merged['pod_capture_type'] = (pod_capture_type or '').strip().casefold()
    if not int(merged.get('video_max_duration_seconds') or 0):
        merged['video_max_duration_seconds'] = POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    if int(merged.get('video_min_count') or 0) > 0 and bool(merged.get('video')):
        merged['video_optional'] = False
    return merged
