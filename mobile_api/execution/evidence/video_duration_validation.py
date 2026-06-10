"""
mobile_api/execution/evidence/video_duration_validation.py

POD / A7 video clip duration enforcement (max 15 seconds).
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from mobile_api.execution.evidence.constants import (
    POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
    VIDEO_MEDIA_TYPES,
)


def video_duration_exceeded_message(
    *,
    max_duration_seconds: int = POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
) -> str:
    return str(
        _(
            'Video length cannot be more than %(max_seconds)s seconds.',
        )
        % {'max_seconds': int(max_duration_seconds)}
    )


def is_video_duration_exceeded(
    *,
    media_type: str,
    duration_seconds: float | None,
    max_duration_seconds: int | None = None,
) -> bool:
    if (media_type or '').strip().casefold() not in VIDEO_MEDIA_TYPES:
        return False
    if duration_seconds is None:
        return False
    limit = int(max_duration_seconds or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS)
    try:
        return float(duration_seconds) > float(limit)
    except (TypeError, ValueError):
        return False
