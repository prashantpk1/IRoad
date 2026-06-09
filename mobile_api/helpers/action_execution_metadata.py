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


def _is_hard_copy_action(action) -> bool:
    if action is None:
        return False
    if getattr(action, 'hard_copy_collection', False):
        return True
    return (getattr(action, 'action_code', '') or '').strip().upper() == 'A7H'

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


def _tenant_evidence_flag(action, field_name: str) -> bool | None:
    """Explicit tenant Action Master flag when present (future portal toggles)."""
    if action is None or not hasattr(action, field_name):
        return None
    return bool(getattr(action, field_name, False))


def infer_requires_photo(action) -> bool:
    if action is None:
        return False
    explicit = _tenant_evidence_flag(action, 'requires_photo')
    if explicit is True:
        return True
    if getattr(action, 'auto_pod_post', False):
        return True
    if _is_hard_copy_action(action):
        return False
    return action_matches(action, *_PHOTO_ACTION_NEEDLES)


def infer_requires_video(action) -> bool:
    if action is None:
        return False
    if _is_hard_copy_action(action):
        return False
    explicit = _tenant_evidence_flag(action, 'requires_video')
    if explicit is True:
        return True
    return action_matches(action, *_VIDEO_ACTION_NEEDLES)


def infer_requires_note(action) -> bool:
    if action is None:
        return False
    if action_matches(action, *_NOTE_ACTION_NEEDLES):
        return True
    return bool((action.booking_status_impact or '').strip())


def build_execution_requirements(action, *, shipment=None) -> dict[str, Any]:
    """Structured capture requirements for mobile execute-action UI."""
    if _is_hard_copy_action(action):
        return {
            'gps': False,
            'photo': False,
            'photo_min_count': 0,
            'video': False,
            'video_min_count': 0,
            'video_max_count': 0,
            'video_optional': False,
            'note': False,
            'note_required': False,
            'signature': False,
            'auto_movement_post': bool(getattr(action, 'auto_movement_post', False)),
            'auto_pod_post': bool(getattr(action, 'auto_pod_post', False)),
            'auto_shipment_post': bool(getattr(action, 'auto_shipment_post', False)),
            'auto_treasury_post': bool(getattr(action, 'auto_treasury_post', False)),
            'hard_copy_collection': True,
            'custody_submission_required': True,
            'capture_mode': 'hard_copy_confirmation',
            'shipment_status_impact': (action.shipment_status_impact or '').strip()
            if action
            else '',
            'movement_status_impact': (action.movement_status_impact or '').strip()
            if action
            else '',
        }

    requires_gps = infer_requires_gps(action)
    requires_photo = infer_requires_photo(action)
    requires_video = infer_requires_video(action)
    requires_note = infer_requires_note(action)
    photo_min = int(getattr(action, 'photo_min_count', None) or 0) if action else 0
    video_min = int(getattr(action, 'video_min_count', None) or 0) if action else 0
    if photo_min <= 0:
        photo_min = 1 if requires_photo and action_matches(
            action,
            'confirm loaded',
            'a4',
            'action 4',
        ) else (1 if requires_photo else 0)
        if requires_photo and action_matches(
            action,
            'upload pod',
            'a7',
            'action 7',
            'hard pod',
            'a7h',
        ):
            photo_min = max(photo_min, 1)
        if requires_photo and getattr(action, 'auto_pod_post', False):
            photo_min = max(photo_min, 1)
    video_max = int(getattr(action, 'video_max_count', None) or 0) if action else 0
    if video_min <= 0 and requires_video:
        video_min = 1 if action_matches(action, 'video', 'record') else 0
    if video_max <= 0 and requires_video:
        video_max = 1
    return {
        'gps': requires_gps,
        'photo': requires_photo,
        'photo_min_count': photo_min,
        'video': requires_video,
        'video_min_count': video_min,
        'video_max_count': video_max,
        'video_optional': bool(getattr(action, 'auto_pod_post', False)),
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
    shipment=None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """
    Mobile allowed-action DTO for one ``TenantOperationAction`` row.
    """
    name = _localized_action_name(action, request)
    if getattr(action, 'auto_pod_post', False) and not _is_hard_copy_action(action):
        from mobile_api.execution.evidence.constants import (
            POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
        )
        from mobile_api.pod_capture.policy.pod_capture_policy import (
            build_pod_capture_requirements,
        )
        from mobile_api.pod_capture.services.pod_section_metadata import (
            build_digital_capture_ui,
        )

        requirements = build_pod_capture_requirements(
            action,
            pod_capture_type='digital',
            shipment=shipment,
        )
        requirements['video_optional'] = False
        requirements['capture_mode'] = 'digital_evidence'
        requirements['screen'] = 'pod_capture'
        requirements['screen_title'] = 'Capturing Action Evidences'
        requirements['video_max_duration_seconds'] = int(
            requirements.get('video_max_duration_seconds')
            or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
        )
        requirements['capture_ui'] = build_digital_capture_ui(requirements)
    else:
        requirements = build_execution_requirements(action, shipment=shipment)
    row = {
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
    if getattr(action, 'auto_pod_post', False) and not _is_hard_copy_action(action):
        row['screen'] = 'pod_capture'
        row['action'] = 'go_to_pod_capture'
        row['capture_mode'] = requirements.get('capture_mode') or 'digital_evidence'
        row['screen_title'] = requirements.get('screen_title') or 'Capturing Action Evidences'
        if requirements.get('capture_ui'):
            row['capture_ui'] = requirements['capture_ui']

    if _is_hard_copy_action(action):
        from mobile_api.helpers.action_navigation_metadata import (
            apply_hard_copy_navigation_to_action_row,
        )

        return apply_hard_copy_navigation_to_action_row(
            row,
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )

    code = (getattr(action, 'action_code', '') or '').strip().upper()
    if code == 'A8':
        row['screen'] = 'job_detail'
        row['action'] = 'execute_action'
        row.pop('capture_mode', None)
        row.pop('capture_ui', None)
        row.pop('screen_title', None)
        requirements = dict(row.get('execution_requirements') or {})
        requirements.update(
            {
                'photo': False,
                'photo_min_count': 0,
                'video': False,
                'video_min_count': 0,
                'video_max_count': 0,
                'video_optional': False,
                'note': False,
                'note_required': False,
                'signature': False,
                'capture_mode': '',
            },
        )
        row['execution_requirements'] = requirements
        row['requires_photo'] = False
        row['requires_video'] = False
        row['requires_note'] = False
    return row


def project_allowed_actions_payload(
    actions,
    *,
    request=None,
    current_stage: str = '',
    context_label: str = '',
    job_type: str = '',
    job_id: str = '',
    job_no: str = '',
    shipment=None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Full allowed-actions response from engine queryset (already filtered)."""
    schema = (tenant_schema or '').strip()
    if not schema and request is not None:
        try:
            from mobile_api.job_detail.services.job_detail_driver_resolver import (
                tenant_schema_for_request,
            )

            schema = tenant_schema_for_request(request)
        except Exception:
            schema = ''

    rows = []
    for action in actions:
        rows.append(
            project_allowed_action_row(
                action,
                request=request,
                current_stage=current_stage,
                sort_index=len(rows),
                shipment=shipment,
                tenant_schema=schema,
            )
        )
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
