"""
mobile_api/job_detail/projections/movement_workflow_status_projection.py

Three-step empty-move workflow for mobile UI (Pickup → In Transit → Delivery).

Step completion is driven only by matching EM action logs — never by column status alone.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.movement_stage_derivation import (
    movement_log_milestone_flags_from_logs,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    is_movement_arrived_action,
    is_movement_complete_action,
    is_movement_in_transit_action,
    is_movement_start_action,
)
from mobile_api.history.projections.history_detail_projection import (
    _display_timestamp,
    _format_timestamp,
    _pick_latest_log_for_codes,
    _serialize_log_media,
)
from mobile_api.job_detail.projections.job_location_projection import (
    build_movement_location_block,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import map_log_to_timeline_event

_MOVEMENT_STEP_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('pickup', 'Pickup', ('EM1',)),
    ('in_transit', 'In Transit', ('EM2',)),
    ('delivery', 'Delivery', ('EM3',)),
)

_TERMINAL_STEP_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('complete', 'Completed', ('EM4',)),
)

_STEP_FLAG_KEYS: dict[str, str] = {
    'pickup': 'start_done',
    'in_transit': 'in_transit_done',
    'delivery': 'arrived_done',
}

_STEP_ACTION_MATCHERS = {
    'pickup': is_movement_start_action,
    'in_transit': is_movement_in_transit_action,
    'delivery': is_movement_arrived_action,
    'complete': is_movement_complete_action,
}


def _pick_log_for_step(
    logs: list[Any],
    *,
    action_codes: tuple[str, ...],
    step_key: str,
) -> Any | None:
    """Resolve the newest log for a workflow step (code match, then lifecycle matcher)."""
    log_row = _pick_latest_log_for_codes(logs, action_codes)
    if log_row is not None:
        return log_row
    matcher = _STEP_ACTION_MATCHERS.get(step_key)
    if matcher is None:
        return None
    matched: list[Any] = []
    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if matcher(action):
            matched.append(log)
    if not matched:
        return None
    matched.sort(
        key=lambda row: (
            getattr(row, 'log_date', None) or getattr(row, 'created_at', None),
        ),
        reverse=True,
    )
    return matched[0]


def _step_is_completed(
    step_key: str,
    *,
    flags: dict[str, bool],
    log_row: Any | None,
) -> bool:
    if log_row is not None:
        return True
    flag_key = _STEP_FLAG_KEYS.get(step_key)
    if flag_key and flags.get(flag_key):
        return True
    if step_key == 'delivery' and flags.get('complete_done'):
        return True
    return False


def build_movement_workflow_status(
    movement: Any,
    logs: list[Any],
    *,
    request: Any | None = None,
) -> list[dict[str, Any]]:
    """
  Ordered workflow steps for empty-move Job Detail.

  ``completed`` is True only when the matching forward action log exists.
    """
    if movement is None:
        return []

    flags = movement_log_milestone_flags_from_logs(logs)
    locations = build_movement_location_block(movement, request=request)
    pickup_address = dict(locations.get('pickup_address') or {})
    drop_address = dict(locations.get('drop_address') or {})

    steps: list[dict[str, Any]] = []
    for step_key, label, codes in _MOVEMENT_STEP_SPECS:
        log_row = _pick_log_for_step(logs, action_codes=codes, step_key=step_key)
        completed = _step_is_completed(step_key, flags=flags, log_row=log_row)
        event = (
            map_log_to_timeline_event(log_row, request=request) if log_row is not None else {}
        )
        step: dict[str, Any] = {
            'step_key': step_key,
            'label': label,
            'completed': completed,
            'timestamp': _format_timestamp(log_row) if log_row else '',
            'display_timestamp': _display_timestamp(log_row) if log_row else '',
            'action_code': event.get('action_code', ''),
            'action_label': event.get('action_label', label),
            'latitude': event.get('latitude', ''),
            'longitude': event.get('longitude', ''),
            'media': _serialize_log_media(log_row) if log_row else [],
        }
        if step_key == 'pickup':
            step['location'] = pickup_address.get('display_name') or pickup_address.get(
                'label', ''
            )
            step['address'] = pickup_address
        elif step_key == 'delivery':
            step['location'] = drop_address.get('display_name') or drop_address.get(
                'label', ''
            )
            step['address'] = drop_address
        steps.append(step)

    if flags.get('complete_done'):
        log_row = _pick_log_for_step(
            logs,
            action_codes=_TERMINAL_STEP_SPECS[0][2],
            step_key='complete',
        )
        event = (
            map_log_to_timeline_event(log_row, request=request) if log_row is not None else {}
        )
        steps.append(
            {
                'step_key': 'complete',
                'label': 'Completed',
                'completed': True,
                'timestamp': _format_timestamp(log_row) if log_row else '',
                'display_timestamp': _display_timestamp(log_row) if log_row else '',
                'action_code': event.get('action_code', 'EM4'),
                'action_label': event.get('action_label', 'Complete Movement'),
                'latitude': event.get('latitude', ''),
                'longitude': event.get('longitude', ''),
                'media': _serialize_log_media(log_row) if log_row else [],
            }
        )

    return steps
