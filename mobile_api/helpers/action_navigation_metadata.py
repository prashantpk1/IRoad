"""
Mobile navigation metadata for Action Master rows (timeline taps, allowed actions).

Hard POD (A7H) uses the custody checklist + ``hard-pod/submit`` flow — not the generic
GPS/photo evidence screen used for movement actions.
"""
from __future__ import annotations

from typing import Any

from mobile_api.pod_capture.services.pod_section_metadata import (
    build_hard_copy_confirmation_block,
)

HARD_COPY_CONFIRMATION_SCREEN = 'hard_copy_confirmation'
POD_CAPTURE_SCREEN = 'pod_capture'
HARD_POD_ACTION_CODE = 'A7H'


def is_hard_copy_navigation_action(action: Any | None) -> bool:
    if action is None:
        return False
    if getattr(action, 'hard_copy_collection', False):
        return True
    return (getattr(action, 'action_code', '') or '').strip().upper() == HARD_POD_ACTION_CODE


def build_hard_copy_navigation_payload(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Checklist contract for Hard POD Collection Confirmation UI."""
    block = build_hard_copy_confirmation_block(
        shipment,
        tenant_schema=tenant_schema,
    )
    if not block.get('required'):
        return {}
    return {
        'screen': HARD_COPY_CONFIRMATION_SCREEN,
        'action': 'go_to_hard_copy_confirmation',
        'hard_copy_confirmation': block,
    }


def apply_hard_copy_navigation_to_action_row(
    row: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """
    Enrich an allowed-action or timeline row so mobile opens the checklist, not evidence capture.
    """
    if not is_hard_copy_navigation_action(action):
        return row

    navigation = build_hard_copy_navigation_payload(
        shipment,
        tenant_schema=tenant_schema,
    )
    if not navigation:
        return row

    row = dict(row)
    row.update(navigation)
    row['requires_gps'] = False
    row['requires_photo'] = False
    row['requires_video'] = False
    row['requires_note'] = False

    requirements = dict(row.get('execution_requirements') or {})
    requirements.update(
        {
            'gps': False,
            'photo': False,
            'photo_min_count': 0,
            'video': False,
            'video_min_count': 0,
            'video_max_count': 0,
            'note': False,
            'note_required': False,
            'hard_copy_collection': True,
            'custody_submission_required': True,
            'capture_mode': HARD_COPY_CONFIRMATION_SCREEN,
        },
    )
    row['execution_requirements'] = requirements
    return row


def enrich_timeline_event_navigation(
    event: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Attach navigation hints to timeline rows (performed or pending)."""
    if not is_hard_copy_navigation_action(action):
        return event
    navigation = build_hard_copy_navigation_payload(
        shipment,
        tenant_schema=tenant_schema,
    )
    if not navigation:
        return event
    out = dict(event)
    out.update(navigation)
    out['capture_mode'] = HARD_COPY_CONFIRMATION_SCREEN
    return out
