"""
Mobile execution metadata for Action Master rows.

IMPORTANT: Allowed-action *membership* is ONLY from ``get_allowed_actions()``.
This module projects UI/evidence metadata from configured action rows — it does
not filter or reorder the policy engine output.
"""

from __future__ import annotations

from typing import Any

from iroad_tenants.operation_execution import action_matches
from mobile_api.helpers.i18n import get_localized_value

# IRoute Ch.2 forward-action evidence conventions (UI metadata only).
_GPS_ACTION_NEEDLES = (
    'start job',
    'a1',
    'action 1',
    'pickup',
    'arrival',
    'a2',
    'action 2',
    'start loading',
    'a3',
    'action 3',
    'depart',
    'in transit',
    'a5',
    'action 5',
    'delivery',
    'arrival',
    'a6',
    'action 6',
    'unloading',
    'a8',
    'action 8',
    'movement',
)

_PHOTO_ACTION_NEEDLES = (
    'confirm loaded',
    'a4',
    'action 4',
    'upload pod',
    'a7',
    'action 7',
    'pod',
)

_VIDEO_ACTION_NEEDLES = (
    'video',
    'record',
)

_NOTE_ACTION_NEEDLES = (
    'collect payment',
    'a9',
    'action 9',
    'cod',
    'note',
)


def _localized_action_name(action, request=None) -> str:
    english = (getattr(action, 'english_label', None) or action.action_code or '').strip()
    arabic = (getattr(action, 'arabic_label', None) or '').strip()
    if request is not None:
        return get_localized_value(request, english, arabic) or action.action_code or ''
    return english or action.action_code or ''


def infer_requires_gps(action) -> bool:
    if action is None:
        return False
    if action_matches(action, *_GPS_ACTION_NEEDLES):
        return True
    return bool((action.movement_status_impact or '').strip())


def infer_requires_photo(action) -> bool:
    if action is None:
        return False
    if getattr(action, 'auto_pod_post', False):
        return True
    if getattr(action, 'hard_copy_collection', False):
        return True
    return action_matches(action, *_PHOTO_ACTION_NEEDLES)


def infer_requires_video(action) -> bool:
    if action is None:
        return False
    return action_matches(action, *_VIDEO_ACTION_NEEDLES)


def infer_requires_note(action) -> bool:
    if action is None:
        return False
    if action_matches(action, *_NOTE_ACTION_NEEDLES):
        return True
    return bool((action.booking_status_impact or '').strip())


def build_execution_requirements(action) -> dict[str, Any]:
    """Structured capture requirements for mobile execute-action UI."""
    requires_gps = infer_requires_gps(action)
    requires_photo = infer_requires_photo(action)
    requires_video = infer_requires_video(action)
    requires_note = infer_requires_note(action)
    photo_min = 1 if requires_photo and action_matches(
        action,
        'confirm loaded',
        'a4',
        'action 4',
    ) else (1 if requires_photo else 0)
    if requires_photo and action_matches(action, 'upload pod', 'a7', 'action 7'):
        photo_min = max(photo_min, 1)
    return {
        'gps': requires_gps,
        'photo': requires_photo,
        'photo_min_count': photo_min,
        'video': requires_video,
        'video_min_count': 1 if requires_video else 0,
        'note': requires_note,
        'note_required': requires_note and action_matches(
            action,
            'collect payment',
            'a9',
            'action 9',
        ),
        'signature': requires_photo and action_matches(
            action,
            'upload pod',
            'a7',
            'action 7',
        ),
        'auto_movement_post': bool(getattr(action, 'auto_movement_post', False)),
        'auto_pod_post': bool(getattr(action, 'auto_pod_post', False)),
        'auto_shipment_post': bool(getattr(action, 'auto_shipment_post', False)),
        'auto_treasury_post': bool(getattr(action, 'auto_treasury_post', False)),
        'hard_copy_collection': bool(getattr(action, 'hard_copy_collection', False)),
        'shipment_status_impact': (action.shipment_status_impact or '').strip()
        if action
        else '',
        'movement_status_impact': (action.movement_status_impact or '').strip()
        if action
        else '',
    }


def resolve_action_category(action) -> str:
    if action is None:
        return ''
    scope = (action.action_scope or '').strip()
    if scope:
        return scope
    return (action.sequence_category or '').strip() or 'job'


def project_allowed_action_row(
    action,
    *,
    request=None,
    current_stage: str = '',
    sort_index: int = 0,
) -> dict[str, Any]:
    """
    Mobile allowed-action DTO for one ``TenantOperationAction`` row.
    """
    name = _localized_action_name(action, request)
    requirements = build_execution_requirements(action)
    return {
        'action_id': str(action.action_id),
        'action_code': action.action_code or '',
        'action_name': name,
        'execution_label': name,
        'requires_gps': requirements['gps'],
        'requires_photo': requirements['photo'],
        'requires_video': requirements['video'],
        'requires_note': requirements['note'],
        'action_category': resolve_action_category(action),
        'execution_order': int(action.sequence_number or 0),
        'sort_index': sort_index,
        'current_stage': current_stage,
        'execution_requirements': requirements,
    }


def project_allowed_actions_payload(
    actions,
    *,
    request=None,
    current_stage: str = '',
    context_label: str = '',
    job_type: str = '',
    job_id: str = '',
    job_no: str = '',
) -> dict[str, Any]:
    """Full allowed-actions response from engine queryset (already filtered)."""
    rows = [
        project_allowed_action_row(
            action,
            request=request,
            current_stage=current_stage,
            sort_index=idx,
        )
        for idx, action in enumerate(actions)
    ]
    primary = rows[0] if rows else None
    return {
        'job_type': job_type,
        'job_id': job_id,
        'job_no': job_no,
        'current_stage': current_stage,
        'context_label': context_label,
        'count': len(rows),
        'actions': rows,
        'primary_action': primary,
        'workflow_source': 'operation_execution.get_allowed_actions',
    }


def resolve_current_stage(*, shipment=None, movement=None) -> str:
    """Reporting-only stage label (not used to filter actions)."""
    if shipment is not None:
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            derive_shipment_execution_stage,
            execution_stage_operational_label,
        )

        stage = derive_shipment_execution_stage(shipment)
        label = execution_stage_operational_label(stage)
        if label:
            return label
        return (getattr(shipment, 'shipment_status', None) or '').strip()
    if movement is not None:
        from iroad_tenants.operation_runtime.movement_stage_derivation import (
            derive_movement_operational_stage,
        )

        label = derive_movement_operational_stage(movement)
        if label:
            return label
        return (getattr(movement, 'status', None) or '').strip()
    return ''
