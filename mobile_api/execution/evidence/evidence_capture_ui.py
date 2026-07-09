"""Mobile layout contract for generic optional evidence capture (Start Job, Pickup, etc.)."""
from __future__ import annotations

from typing import Any

from mobile_api.execution.evidence.constants import (
    EXECUTION_MEDIA_MAX_PHOTOS,
    POD_CAPTURE_VIDEO_MAX_COUNT,
    POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
)
from mobile_api.helpers.evidence_requirement_flags import normalize_evidence_requirements
from mobile_api.pod_capture.services.pod_section_metadata import (
    DIGITAL_EVIDENCE_SCREEN_TITLE,
)

UI_MODE_OPTIONAL_EVIDENCE = 'optional_evidence'
UI_MODE_STANDALONE_EVIDENCE = 'standalone_evidence'

ISSUE_REPORT_SUBMIT_ENDPOINT = '/api/v1/mobile/driver/issues/report/'
EXECUTE_ACTION_SUBMIT_ENDPOINT = '/api/v1/mobile/driver/jobs/execute/'


def build_media_evidence_sections(
    requirements: dict[str, Any],
    *,
    include_note: bool = False,
) -> list[dict[str, Any]]:
    """
    Photo + video slots for every driver evidence screen.

    Slots are always listed; enforcement is driven only by min_count / required flags.
    """
    req = normalize_evidence_requirements(requirements)
    photo_min = int(req.get('photo_min_count') or 0)
    video_min = int(req.get('video_min_count') or 0)
    photo_required = photo_min > 0
    video_required = video_min > 0
    video_max_seconds = int(
        req.get('video_max_duration_seconds') or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    )
    sections: list[dict[str, Any]] = [
        {
            'id': 'evidence_photos',
            'label': 'Add Evidence Photos',
            'media_type': 'photo',
            'required': photo_required,
            'optional': not photo_required,
            'min_count': photo_min,
            'max_count': int(req.get('photo_max_count') or 0) or EXECUTION_MEDIA_MAX_PHOTOS,
            'capture_label': 'Capture Photos',
            'visible': True,
            'skippable': True,
            'enforce_min_count': False,
        },
        {
            'id': 'evidence_video',
            'label': 'Add Evidence Video',
            'media_type': 'video',
            'required': video_required,
            'optional': not video_required,
            'min_count': video_min,
            'max_count': int(req.get('video_max_count') or 0) or POD_CAPTURE_VIDEO_MAX_COUNT,
            'max_duration_seconds': video_max_seconds,
            'capture_label': f'Record Video Clip (max {video_max_seconds}s)',
            'visible': True,
            'skippable': True,
            'enforce_min_count': False,
        },
    ]
    if include_note or bool(req.get('note')):
        note_required = bool(req.get('note_required'))
        sections.append(
            {
                'id': 'note',
                'label': 'Note',
                'media_type': 'note',
                'required': note_required,
                'optional': not note_required,
                'placeholder': 'Write a note...',
                'visible': True,
            },
        )
    return sections


def build_generic_evidence_capture_ui(
    requirements: dict[str, Any],
    *,
    action_code: str = '',
    screen_title: str = '',
) -> dict[str, Any]:
    """Layout for ``evidence_capture`` screen — photo/video always shown, optional by default."""
    req = normalize_evidence_requirements(requirements)
    title = (screen_title or '').strip() or DIGITAL_EVIDENCE_SCREEN_TITLE
    video_max_seconds = int(
        req.get('video_max_duration_seconds') or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    )
    photo_min = int(req.get('photo_min_count') or 0)
    video_min = int(req.get('video_min_count') or 0)
    photo_required = photo_min > 0
    video_required = video_min > 0
    allow_empty = bool(req.get('allow_submit_without_media'))
    return {
        'ui_mode': UI_MODE_OPTIONAL_EVIDENCE,
        'screen_title': title,
        'show_photo': True,
        'show_video': True,
        'requires_photo': False,
        'requires_video': False,
        'photo_optional': True,
        'photo_mandatory': False,
        'video_optional': True,
        'video_mandatory': False,
        'video_max_duration_seconds': video_max_seconds,
        'allow_submit_without_media': allow_empty,
        'gps_banner': {
            'label': 'GPS captured + Evidence Media',
            'subtitle': f'Video clips must be max {video_max_seconds} seconds.',
            'required': bool(req.get('gps')),
        },
        'sections': build_media_evidence_sections(req, include_note=True),
        'footer_hint': (
            'Photos, videos, and notes are optional. Tap Next to continue without media.'
            if allow_empty
            else 'Complete required evidence before continuing.'
        ),
        'submit_validation': {
            'photo_min_count': photo_min,
            'video_min_count': video_min,
            'photo_required': photo_required,
            'video_required': video_required,
            'video_max_count': int(req.get('video_max_count') or 0) or POD_CAPTURE_VIDEO_MAX_COUNT,
            'video_max_duration_seconds': video_max_seconds,
            'allow_empty_media': allow_empty,
        },
        'primary_button': {
            'label': 'Next',
            'action': 'submit_evidence',
            'execute_action_code': (action_code or '').strip(),
            'complete_upload_after_execute': False,
            'allow_empty_media': allow_empty,
            'photo_required': False,
            'video_required': False,
            'requires_photo': False,
            'requires_video': False,
        },
    }


def build_standalone_evidence_capture_ui(
    requirements: dict[str, Any],
    *,
    action_code: str = '',
    screen_title: str = '',
    submit_button_label: str = 'Submit',
) -> dict[str, Any]:
    """
    Evidence layout not tied to job sequence or empty-move workflow.

    Used for support reporting and ``without``-scope Operation Actions.
    """
    ui = build_generic_evidence_capture_ui(
        requirements,
        action_code=action_code,
        screen_title=screen_title,
    )
    req = requirements
    ui['ui_mode'] = UI_MODE_STANDALONE_EVIDENCE
    ui['linked_job_flow'] = False
    ui['show_context_card'] = False
    gps_required = bool(req.get('gps'))
    ui['gps_banner'] = {
        'label': 'GPS location',
        'subtitle': 'Latitude and longitude are required before submit.',
        'required': gps_required,
    }
    ui['requires_gps'] = gps_required
    ui['primary_button'] = {
        **dict(ui.get('primary_button') or {}),
        'label': (submit_button_label or 'Submit').strip(),
        'action': 'submit_evidence',
        'execute_action_code': (action_code or '').strip(),
        'allow_empty_media': bool(ui.get('allow_submit_without_media')),
        'requires_gps': gps_required,
    }
    return ui
