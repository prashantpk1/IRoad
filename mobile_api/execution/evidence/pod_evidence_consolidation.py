"""
mobile_api/execution/evidence/pod_evidence_consolidation.py

Collapse fragmented / repeated POD staging rows before A7 validation.

Each retry of ``pod/capture`` can leave another READY bundle. Auto-merge for
execute must satisfy photo + signature + video without exceeding per-type caps.
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.evidence.constants import (
    EXECUTION_MEDIA_MAX_PHOTOS,
    POD_CAPTURE_VIDEO_MAX_COUNT,
)


def is_pod_capture_requirements(requirements: dict[str, Any] | None) -> bool:
    data = requirements or {}
    return bool(data.get('signature')) or int(data.get('video_max_count') or 0) > 0


def consolidate_pod_evidence_dicts(
    rows: list[dict[str, Any]],
    requirements: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep the latest rows per media type within POD policy caps."""
    if not rows or not is_pod_capture_requirements(requirements):
        return list(rows)

    photo_cap = int(requirements.get('photo_max_count') or 0) or EXECUTION_MEDIA_MAX_PHOTOS
    video_cap = int(requirements.get('video_max_count') or 0) or POD_CAPTURE_VIDEO_MAX_COUNT
    sig_cap = 1 if bool(requirements.get('signature')) else 0

    buckets: dict[str, list[dict[str, Any]]] = {
        'photo': [],
        'signature': [],
        'video': [],
        'document': [],
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        media_type = str(row.get('media_type') or '').strip().casefold()
        if media_type in buckets:
            buckets[media_type].append(row)

    return (
        buckets['photo'][-photo_cap:]
        + buckets['signature'][-sig_cap:]
        + buckets['video'][-video_cap:]
        + buckets['document']
    )


def consolidate_pod_evidence_items(
    items: list[Any],
    requirements: dict[str, Any],
) -> list[Any]:
    """Namespace / dataclass variant for execute validation."""
    if not items or not is_pod_capture_requirements(requirements):
        return list(items)

    photo_cap = int(requirements.get('photo_max_count') or 0) or EXECUTION_MEDIA_MAX_PHOTOS
    video_cap = int(requirements.get('video_max_count') or 0) or POD_CAPTURE_VIDEO_MAX_COUNT
    sig_cap = 1 if bool(requirements.get('signature')) else 0

    buckets: dict[str, list[Any]] = {
        'photo': [],
        'signature': [],
        'video': [],
        'document': [],
    }
    for item in items:
        media_type = str(getattr(item, 'media_type', '') or '').strip().casefold()
        if media_type in buckets:
            buckets[media_type].append(item)

    return (
        buckets['photo'][-photo_cap:]
        + buckets['signature'][-sig_cap:]
        + buckets['video'][-video_cap:]
        + buckets['document']
    )
