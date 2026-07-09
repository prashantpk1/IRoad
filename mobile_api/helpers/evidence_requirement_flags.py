"""Shared evidence requirement flags for mobile API projections."""
from __future__ import annotations

from typing import Any

from mobile_api.execution.evidence.constants import (
    POD_CAPTURE_VIDEO_MAX_COUNT,
    POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
)


def media_required(requirements: dict[str, Any], media_key: str) -> bool:
    """True only when tenant min-count enforcement applies."""
    min_key = f'{media_key}_min_count'
    return int(requirements.get(min_key) or 0) > 0


def normalize_evidence_requirements(requirements: dict[str, Any]) -> dict[str, Any]:
    """
    Split UI visibility from enforcement.

    Mobile clients historically treated ``photo: true`` as mandatory. After
    normalization:

    * ``photo_enabled`` / ``video_enabled`` — show capture slots
    * ``photo`` / ``video`` — enforcement only (true when min_count > 0)
  * ``allow_submit_without_media`` — explicit submit-without-files hint
    """
    req = dict(requirements or {})
    photo_min = max(int(req.get('photo_min_count') or 0), 0)
    video_min = max(int(req.get('video_min_count') or 0), 0)

    is_hard_copy = bool(req.get('hard_copy_collection')) and not bool(
        req.get('auto_pod_post'),
    )
    # Driver evidence screens: photo and video are optional (video max 60s when provided).
    if not is_hard_copy:
        photo_min = 0
        video_min = 0

    photo_enabled = bool(req.get('photo_enabled'))
    if not photo_enabled:
        photo_enabled = photo_min > 0 or (
            bool(req.get('photo')) and photo_min <= 0
        )
    video_enabled = bool(req.get('video_enabled'))
    if not video_enabled:
        video_enabled = video_min > 0 or bool(req.get('video'))

    if not is_hard_copy:
        photo_enabled = True
        video_enabled = True

    if req.get('requires_evidence_capture') or req.get('capture_mode') in {
        'optional_evidence',
        'digital_evidence',
    }:
        photo_enabled = True
        video_enabled = True
        req.setdefault('note', True)
        req['note_required'] = False

    req['photo_enabled'] = photo_enabled
    req['video_enabled'] = video_enabled
    req['photo_min_count'] = photo_min
    req['video_min_count'] = video_min
    req['photo'] = False
    req['video'] = False
    req['photo_optional'] = True
    req['video_optional'] = True
    req['photo_mandatory'] = False
    req['video_mandatory'] = False
    req['requires_photo'] = False
    req['requires_video'] = False
    if not is_hard_copy:
        if not int(req.get('video_max_duration_seconds') or 0):
            req['video_max_duration_seconds'] = POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
        if not int(req.get('video_max_count') or 0):
            req['video_max_count'] = POD_CAPTURE_VIDEO_MAX_COUNT
    req['allow_submit_without_media'] = (
        photo_min <= 0
        and video_min <= 0
        and not bool(req.get('signature'))
    )
    return req


def sync_row_evidence_flags(row: dict[str, Any]) -> dict[str, Any]:
    """Align top-level flags with normalized execution_requirements."""
    out = dict(row)
    requirements = normalize_evidence_requirements(
        dict(out.get('execution_requirements') or {}),
    )
    out['execution_requirements'] = requirements
    out['requires_gps'] = bool(requirements.get('gps'))
    out['requires_photo'] = media_required(requirements, 'photo')
    out['requires_video'] = media_required(requirements, 'video')
    out['photo_optional'] = bool(requirements.get('photo_optional'))
    out['photo_mandatory'] = bool(requirements.get('photo_mandatory'))
    out['video_optional'] = bool(requirements.get('video_optional'))
    out['video_mandatory'] = bool(requirements.get('video_mandatory'))
    out['requires_note'] = bool(requirements.get('note_required'))
    out['show_photo'] = bool(requirements.get('photo_enabled'))
    out['show_video'] = bool(requirements.get('video_enabled'))
    capture_modes = {'optional_evidence', 'digital_evidence'}
    out['show_note'] = bool(requirements.get('note')) or bool(
        requirements.get('requires_evidence_capture'),
    ) or (requirements.get('capture_mode') in capture_modes)
    out['video_max_duration_seconds'] = int(
        requirements.get('video_max_duration_seconds')
        or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    )
    out['allow_submit_without_media'] = bool(
        requirements.get('allow_submit_without_media'),
    )
    return out
