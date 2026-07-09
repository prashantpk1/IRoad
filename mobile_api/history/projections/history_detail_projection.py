"""
mobile_api/history/projections/history_detail_projection.py

Read-only History Detail — summary + workflow milestones (§14.7.1).

Timeline is derived from append-only Action Log rows (Engine Principle P1).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings

from mobile_api.history.projections.history_card_projection import (
    _address_city,
    _address_full,
    _client_name,
    final_state_labels,
    payment_method_tag,
    resolve_history_route,
    resolve_job_date,
    resolve_trip_type,
    route_type_label,
)
from mobile_api.job_detail.projections.job_location_projection import (
    build_shipment_location_block,
)
from mobile_api.history.selectors.order_type_resolver import resolve_order_type
from mobile_api.history.projections.history_milestone_resolver import (
    _tenant_schema_from_request,
    milestone_completed_for_history,
    pick_log_for_history_milestone,
    resolve_history_milestone_specs,
)
from mobile_api.history.projections.history_timeline_projection import (
    _find_log_for_event,
    _pick_timeline_event_for_step,
    build_history_timeline_events,
    index_timeline_events_by_step_key,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import map_log_to_timeline_event
from tenant_workspace.models import TenantOperationActionMedia
from tenant_workspace.ops_display import resolve_shipment_truck, truck_display_block


def _media_url(media_row: TenantOperationActionMedia) -> str:
    file_field = getattr(media_row, 'file', None)
    if file_field and getattr(file_field, 'name', ''):
        try:
            return file_field.url
        except Exception:
            pass
    return ''


def _serialize_log_media(log_row: Any) -> list[dict[str, Any]]:
    rows = list(getattr(log_row, 'media_rows', []).all()) if hasattr(log_row, 'media_rows') else []
    payload: list[dict[str, Any]] = []
    for row in rows:
        payload.append(
            {
                'media_id': str(getattr(row, 'media_id', '') or row.pk or ''),
                'media_type': str(getattr(row, 'media_type', '') or ''),
                'file_url': _media_url(row),
                'description': str(getattr(row, 'description', '') or ''),
                'captured_at': (
                    row.captured_at.isoformat()
                    if getattr(row, 'captured_at', None) is not None
                    else ''
                ),
            }
        )
    return payload


def _format_timestamp(log_row: Any) -> str:
    log_date = getattr(log_row, 'log_date', None)
    if log_date is not None and hasattr(log_date, 'isoformat'):
        return log_date.isoformat()
    created = getattr(log_row, 'created_at', None)
    if created is not None and hasattr(created, 'isoformat'):
        return created.isoformat()
    return ''


def _display_timestamp(log_row: Any) -> str:
    """Human-friendly timestamp for mobile UI (date | time)."""
    log_date = getattr(log_row, 'log_date', None)
    if log_date is None:
        return ''
    try:
        localized = timezone_local(log_date)
        return localized.strftime('%d %b %Y | %I:%M %p')
    except Exception:
        return _format_timestamp(log_row)


def timezone_local(dt):
    from django.utils import timezone as dj_tz

    if dj_tz.is_aware(dt):
        return dj_tz.localtime(dt)
    return dj_tz.make_aware(dt, dj_tz.get_current_timezone())


def _pick_latest_log_for_codes(
    logs: list[Any],
    action_codes: tuple[str, ...],
    *,
    step_key: str = '',
) -> Any | None:
    if step_key:
        return pick_log_for_history_milestone(
            logs,
            step_key=step_key,
            action_codes=action_codes,
        )
    codes = {c.strip().casefold() for c in action_codes if c}
    matched = []
    for log in logs:
        action = getattr(log, 'operation_action', None)
        code = str(getattr(action, 'action_code', '') or '').strip().casefold()
        if code in codes:
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


def build_workflow_status(
    shipment: Any,
    logs: list[Any],
    *,
    request: Any | None = None,
) -> list[dict[str, Any]]:
    """
    Ordered workflow steps for History Detail (read-only).

    Uses Action Master merge (same as Job Detail) so renamed OA-* codes and
    booking-line COD still produce POD / unloading / payment / close rows.
    """
    booking = getattr(shipment, 'booking', None)
    cargo = getattr(shipment, 'cargo', None)
    cargo_name = ''
    if cargo is not None:
        cargo_name = str(
            getattr(cargo, 'name_english', '')
            or getattr(cargo, 'display_name', '')
            or getattr(cargo, 'cargo_name', '')
            or ''
        ).strip()

    order_type = resolve_order_type(shipment, booking)
    tenant_schema = _tenant_schema_from_request(request)
    milestone_specs = resolve_history_milestone_specs(
        order_type=order_type,
        tenant_schema=tenant_schema,
    )
    route = resolve_history_route(shipment, booking, request=request)
    payment_tag = payment_method_tag(shipment, booking)
    location_block = build_shipment_location_block(
        shipment,
        booking=booking,
        request=request,
    )
    pickup_address = dict(location_block.get('pickup_address') or {})
    drop_address = dict(location_block.get('drop_address') or {})

    timeline_events, workflow_actions = build_history_timeline_events(
        shipment,
        logs,
        booking=booking,
        request=request,
    )
    events_by_step = index_timeline_events_by_step_key(timeline_events, workflow_actions)

    steps: list[dict[str, Any]] = []
    for step_key, label, codes in milestone_specs:
        timeline_event = _pick_timeline_event_for_step(
            events_by_step.get(step_key, []),
            step_key=step_key,
        )
        log_row = _find_log_for_event(timeline_event, logs)
        if log_row is None:
            log_row = pick_log_for_history_milestone(
                logs,
                step_key=step_key,
                action_codes=codes,
            )
        completed = milestone_completed_for_history(
            shipment,
            step_key,
            log_row,
            order_type=order_type,
        )
        event = (
            map_log_to_timeline_event(log_row, request=request) if log_row is not None else {}
        )
        if timeline_event and not event:
            event = dict(timeline_event)

        step: dict[str, Any] = {
            'step_key': step_key,
            'label': label,
            'completed': completed,
            'timestamp': (
                _format_timestamp(log_row)
                if log_row
                else str(timeline_event.get('log_date') or timeline_event.get('created_at') or '')
                if timeline_event
                else ''
            ),
            'display_timestamp': (
                _display_timestamp(log_row)
                if log_row
                else _display_timestamp_from_event(timeline_event)
            ),
            'action_code': event.get('action_code', ''),
            'action_label': event.get('action_label', label),
            'latitude': event.get('latitude', ''),
            'longitude': event.get('longitude', ''),
            'media': _serialize_log_media(log_row) if log_row else [],
        }

        if step_key == 'pickup':
            step['location'] = (
                pickup_address.get('label')
                or pickup_address.get('display_name')
                or route['from_location']
            )
            step['shipment_no'] = str(getattr(shipment, 'shipment_no', '') or '')
        elif step_key == 'loading':
            step['cargo_description'] = cargo_name
            step['payment_type'] = payment_tag
        elif step_key == 'delivery':
            step['location'] = (
                drop_address.get('label')
                or drop_address.get('display_name')
                or route['to_location']
            )
        elif step_key == 'pod' and step['media']:
            step['pod_preview_url'] = step['media'][0].get('file_url', '')

        if completed:
            steps.append(step)

    return steps


def _display_timestamp_from_event(event: dict[str, Any] | None) -> str:
    if not event:
        return ''
    raw = str(event.get('log_date') or event.get('created_at') or '').strip()
    if not raw:
        return ''
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return timezone_local(parsed).strftime('%d %b %Y | %I:%M %p')
    except Exception:
        return raw


def build_history_detail(
    shipment: Any,
    logs: list[Any],
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Full History Detail payload (summary + workflow + timeline audit)."""
    booking = getattr(shipment, 'booking', None)
    location_block = build_shipment_location_block(
        shipment,
        booking=booking,
        request=request,
    )
    pickup_address = dict(location_block.get('pickup_address') or {})
    drop_address = dict(location_block.get('drop_address') or {})
    route = resolve_history_route(shipment, booking, request=request)
    display_status, final_state = final_state_labels(shipment)
    job_date = resolve_job_date(shipment, booking)
    order_type = resolve_order_type(shipment, booking)
    truck = resolve_shipment_truck(shipment, booking)

    summary = {
        'shipment_id': str(getattr(shipment, 'shipment_id', None) or shipment.pk or ''),
        'shipment_no': str(getattr(shipment, 'shipment_no', '') or ''),
        'booking_id': str(getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None) or '')
        if booking
        else '',
        'booking_no': str(getattr(booking, 'booking_no', '') or '') if booking else '',
        'status': display_status,
        'final_state': final_state,
        'route_type': route_type_label(booking, shipment),
        'order_type': order_type,
        'payment_method': order_type,
        'transaction_type': order_type,
        'from_location': route['from_location'],
        'to_location': route['to_location'],
        'route_display': route['route_display'],
        'route': {
            'route_display': route['route_display'],
            'route_display_start': route['route_display_start'],
            'route_display_end': route['route_display_end'],
            'route_direction': route['route_direction'],
            'route_id': route['route_id'],
            'route_code': route['route_code'],
            'route_label': route['route_label'],
            'route_type': route['route_type'],
        },
        'truck': truck_display_block(truck),
        'origin': {
            'city': route['origin_city'] or pickup_address.get('city', ''),
            'address': (
                pickup_address.get('label')
                or pickup_address.get('display_name')
                or route['from_location']
            ),
        },
        'destination': {
            'city': route['destination_city'] or drop_address.get('city', ''),
            'address': (
                drop_address.get('label')
                or drop_address.get('display_name')
                or route['to_location']
            ),
        },
        'client_name': _client_name(shipment, booking),
        'job_date': job_date.isoformat() if job_date else '',
        'shipment_date': (
            getattr(shipment, 'shipment_date', None).isoformat()
            if getattr(shipment, 'shipment_date', None)
            else ''
        ),
        'read_only': True,
    }

    timeline_events = [
        map_log_to_timeline_event(row, request=request)
        for row in sorted(
            logs,
            key=lambda row: (
                getattr(row, 'log_date', None) or getattr(row, 'created_at', None),
            ),
        )
    ]

    workflow_timeline, _workflow_actions = build_history_timeline_events(
        shipment,
        logs,
        booking=booking,
        request=request,
    )
    timeline_preview = [
        row for row in workflow_timeline if row.get('is_performed')
    ]

    actions_fired_count = sum(
        1
        for row in logs
        if getattr(row, 'operation_action', None) is not None
        and not getattr(getattr(row, 'operation_action', None), 'admin_only', False)
    )

    return {
        'trip_type': resolve_trip_type(booking, shipment),
        'pickup_address': location_block.get('pickup_address') or {},
        'drop_address': location_block.get('drop_address') or {},
        'summary': summary,
        'workflow_status': build_workflow_status(shipment, logs, request=request),
        'timeline_preview': timeline_preview,
        'timeline': {
            'scope': 'shipment',
            'events': timeline_events,
            'timeline_preview': timeline_preview,
            'append_only': True,
            'authority': 'action_log',
        },
        'actions_fired_count': actions_fired_count,
        'history_projection_version': str(
            getattr(settings, 'MOBILE_HISTORY_PROJECTION_VERSION', '4')
        ),
    }
