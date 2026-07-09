"""
mobile_api/job_detail/projections/movement_workflow_status_projection.py

Dynamic empty-move workflow for mobile UI — one step per tenant Action Master
row with ``sequence_category = empty_move``, ordered by ``sequence_number``.

Step completion is driven only by matching action logs for that step's code.
"""
from __future__ import annotations

from typing import Any, Literal

from iroad_tenants.operation_runtime.movement_stage_derivation import (
    _apply_log_to_milestone_flags,
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
    _serialize_log_media,
)
from mobile_api.job_detail.projections.job_location_projection import (
    _empty_move_arrival_endpoint_block,
    build_movement_location_block,
    gps_empty_move_endpoint_block,
)
from mobile_api.helpers.empty_move_action_resolver import (
    resolve_empty_move_action_for_step,
    resolve_empty_move_workflow_step_specs,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import map_log_to_timeline_event

_LEGACY_STEP_FLAG_KEYS: dict[str, str] = {
    'pickup': 'start_done',
    'in_transit': 'in_transit_done',
    'delivery': 'arrived_done',
    'complete': 'complete_done',
}

_LEGACY_STEP_ACTION_MATCHERS = {
    'pickup': is_movement_start_action,
    'in_transit': is_movement_in_transit_action,
    'delivery': is_movement_arrived_action,
    'complete': is_movement_complete_action,
}


def _movement_workflow_flags_from_logs(logs: list[Any]) -> dict[str, bool]:
    """Direct log milestones only — no forward cascade."""
    flags = {
        'start_done': False,
        'in_transit_done': False,
        'arrived_done': False,
        'complete_done': False,
    }
    for log in logs or []:
        _apply_log_to_milestone_flags(flags, log)
    return flags


def _pick_log_for_step(
    logs: list[Any],
    *,
    action_codes: tuple[str, ...],
    step_key: str,
) -> Any | None:
    """Newest matching empty-move log (code first, then legacy lifecycle matcher)."""
    codes = {c.strip().casefold() for c in action_codes if c}
    matched: list[Any] = []
    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        code = str(getattr(action, 'action_code', '') or '').strip().casefold()
        if code and code in codes:
            matched.append(log)
            continue
        matcher = _LEGACY_STEP_ACTION_MATCHERS.get(step_key)
        if matcher is not None and matcher(action):
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
    flag_key = _LEGACY_STEP_FLAG_KEYS.get(step_key)
    if flag_key and flags.get(flag_key):
        return True
    return False


def _apply_gps_endpoint_to_step(
    step: dict[str, Any],
    movement: Any,
    side: Literal['from', 'to'],
    *,
    request: Any | None = None,
    log_row: Any | None = None,
    event: dict[str, Any] | None = None,
) -> None:
    """Populate workflow step + address with GPS lat/lng for Start Job / End Job."""
    event = event or {}
    log_lat = str(event.get('latitude') or '').strip()
    log_lng = str(event.get('longitude') or '').strip()
    if log_row is not None and not (log_lat and log_lng):
        log_lat = str(getattr(log_row, 'latitude', '') or '').strip()
        log_lng = str(getattr(log_row, 'longitude', '') or '').strip()

    route_address_override = ''
    if log_row is not None:
        route_address_override = str(
            getattr(log_row, '_route_location_address', '') or '',
        ).strip()

    if side == 'to':
        address = _empty_move_arrival_endpoint_block(
            movement,
            request=request,
            log_latitude=log_lat,
            log_longitude=log_lng,
            address_override=route_address_override,
        )
    else:
        address = gps_empty_move_endpoint_block(
            movement,
            side,
            request=request,
            log_latitude=log_lat,
            log_longitude=log_lng,
            address_override=route_address_override,
        )
    step['location_capture_mode'] = 'gps'
    step['gps_capture_required'] = True
    if address:
        lat = str(address.get('latitude') or '').strip()
        lng = str(address.get('longitude') or '').strip()
        step['latitude'] = lat
        step['longitude'] = lng
        step['location'] = address.get('display_name') or address.get('label') or ''
        step['address'] = address
    else:
        step['latitude'] = ''
        step['longitude'] = ''
        step['location'] = ''
        step['address'] = {}


def build_movement_workflow_status(
    movement: Any,
    logs: list[Any],
    *,
    request: Any | None = None,
    tenant_schema: str = '',
) -> list[dict[str, Any]]:
    """
    Ordered workflow steps for empty-move Job Detail.

    ``completed`` is True only when the matching action log exists for that step.
    """
    if movement is None:
        return []

    schema = (tenant_schema or '').strip()
    if not schema and request is not None:
        try:
            from mobile_api.job_detail.services.job_detail_driver_resolver import (
                tenant_schema_for_request,
            )

            schema = tenant_schema_for_request(request)
        except Exception:
            schema = ''

    movement_step_specs = resolve_empty_move_workflow_step_specs(schema)
    if not movement_step_specs:
        return []

    flags = _movement_workflow_flags_from_logs(logs)
    locations = build_movement_location_block(
        movement,
        request=request,
        movement_logs=logs,
    )
    pickup_address = dict(locations.get('pickup_address') or {})
    drop_address = dict(locations.get('drop_address') or {})
    delivery_address = dict(locations.get('delivery_address') or {})

    step_count = len(movement_step_specs)
    steps: list[dict[str, Any]] = []
    for index, (step_key, label, codes) in enumerate(movement_step_specs):
        log_row = _pick_log_for_step(logs, action_codes=codes, step_key=step_key)
        completed = _step_is_completed(step_key, flags=flags, log_row=log_row)
        event = (
            map_log_to_timeline_event(log_row, request=request) if log_row is not None else {}
        )
        resolved_action = (
            getattr(log_row, 'operation_action', None) if log_row is not None else None
        )
        if resolved_action is None and schema:
            resolved_action = resolve_empty_move_action_for_step(step_key, schema)
        action_id = ''
        if resolved_action is not None:
            action_id = str(getattr(resolved_action, 'action_id', '') or '').strip()

        step: dict[str, Any] = {
            'step_key': step_key,
            'label': label,
            'completed': completed,
            'is_performed': completed,
            'timeline_state': 'performed' if completed else 'pending',
            'timestamp': _format_timestamp(log_row) if log_row else '',
            'display_timestamp': _display_timestamp(log_row) if log_row else '',
            'action_code': event.get('action_code', codes[0] if codes else ''),
            'action_label': event.get('action_label', label),
            'latitude': '',
            'longitude': '',
            'media': _serialize_log_media(log_row) if log_row else [],
        }
        if action_id:
            step['action_id'] = action_id
        if index == 0:
            _apply_gps_endpoint_to_step(
                step,
                movement,
                'from',
                request=request,
                log_row=log_row,
                event=event,
            )
            if not step.get('address') and pickup_address:
                step['location'] = pickup_address.get('display_name') or pickup_address.get(
                    'label', '',
                )
                step['address'] = dict(pickup_address)
        elif index == step_count - 1:
            step['location_capture_mode'] = 'gps'
            step['gps_capture_required'] = True
            if log_row is not None:
                _apply_gps_endpoint_to_step(
                    step,
                    movement,
                    'to',
                    request=request,
                    log_row=log_row,
                    event=event,
                )
                if not (step.get('address') or {}).get('to_address') and delivery_address.get(
                    'to_address',
                ):
                    merged = dict(delivery_address)
                    if step.get('latitude'):
                        merged['latitude'] = step['latitude']
                    if step.get('longitude'):
                        merged['longitude'] = step['longitude']
                    step['address'] = merged
                    step['location'] = (
                        merged.get('to_address')
                        or merged.get('display_name')
                        or merged.get('label')
                        or step.get('location', '')
                    )
            elif flags.get('in_transit_done'):
                arrival = _empty_move_arrival_endpoint_block(
                    movement,
                    request=request,
                )
                step['latitude'] = str(arrival.get('latitude') or '')
                step['longitude'] = str(arrival.get('longitude') or '')
                step['location'] = arrival.get('display_name') or arrival.get(
                    'label', '',
                )
                step['address'] = dict(arrival)
                step['awaiting_arrival_gps'] = bool(arrival.get('awaiting_arrival_gps'))
            else:
                step['latitude'] = ''
                step['longitude'] = ''
                step['location'] = ''
                step['address'] = {}
        steps.append(step)

    return steps
