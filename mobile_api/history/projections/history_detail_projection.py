"""
mobile_api/history/projections/history_detail_projection.py

Read-only History Detail — summary + workflow milestones (§14.7.1).

Timeline is derived from append-only Action Log rows (Engine Principle P1).
"""
from __future__ import annotations

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
from mobile_api.job_detail.timeline.timeline_event_mapper import map_log_to_timeline_event
from tenant_workspace.models import TenantOperationActionMedia
from tenant_workspace.ops_display import resolve_shipment_truck, truck_display_block

# Canonical forward-action milestones for the History Detail UI.
_MILESTONE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ('pickup', 'Pickup', ('A2',)),
    ('loading', 'Loading', ('A3', 'A4')),
    ('in_transit', 'In Transit', ('A5',)),
    ('delivery', 'Delivery', ('A6',)),
    ('pod', 'POD', ('A7',)),
    ('unloading', 'Unloading Completed', ('A8',)),
    ('payment', 'Collect Payment', ('A9',)),
    ('job_closed', 'Shipment Completed', ('A10',)),
)


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
) -> Any | None:
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

    Each step is completed when a matching forward Action Log exists.
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

    loading_address = getattr(shipment, 'loading_address', None)
    delivery_address = getattr(shipment, 'delivery_address', None)
    if loading_address is None and booking is not None:
        loading_address = getattr(booking, 'loading_address', None)
    if delivery_address is None and booking is not None:
        delivery_address = getattr(booking, 'delivery_address', None)
    route = resolve_history_route(shipment, booking)
    payment_tag = payment_method_tag(shipment, booking)

    steps: list[dict[str, Any]] = []
    for step_key, label, codes in _MILESTONE_SPECS:
        log_row = _pick_latest_log_for_codes(logs, codes)
        completed = log_row is not None
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
            step['location'] = _address_full(loading_address) or route['from_location']
            step['shipment_no'] = str(getattr(shipment, 'shipment_no', '') or '')
        elif step_key == 'loading':
            step['cargo_description'] = cargo_name
            step['payment_type'] = payment_tag
        elif step_key == 'delivery':
            step['location'] = _address_full(delivery_address) or route['to_location']
        elif step_key == 'pod' and step['media']:
            step['pod_preview_url'] = step['media'][0].get('file_url', '')

        steps.append(step)

    return steps


def build_history_detail(
    shipment: Any,
    logs: list[Any],
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Full History Detail payload (summary + workflow + timeline audit)."""
    booking = getattr(shipment, 'booking', None)
    loading = getattr(shipment, 'loading_address', None)
    delivery = getattr(shipment, 'delivery_address', None)
    if loading is None and booking is not None:
        loading = getattr(booking, 'loading_address', None)
    if delivery is None and booking is not None:
        delivery = getattr(booking, 'delivery_address', None)
    route = resolve_history_route(shipment, booking)
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
            'city': route['origin_city'] or _address_city(loading),
            'address': _address_full(loading) or route['from_location'],
        },
        'destination': {
            'city': route['destination_city'] or _address_city(delivery),
            'address': _address_full(delivery) or route['to_location'],
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

    actions_fired_count = sum(
        1
        for row in logs
        if getattr(row, 'operation_action', None) is not None
        and not getattr(getattr(row, 'operation_action', None), 'admin_only', False)
    )

    location_block = build_shipment_location_block(
        shipment,
        booking=booking,
        request=request,
    )

    return {
        'trip_type': resolve_trip_type(booking, shipment),
        'pickup_address': location_block.get('pickup_address') or {},
        'drop_address': location_block.get('drop_address') or {},
        'summary': summary,
        'workflow_status': build_workflow_status(shipment, logs, request=request),
        'timeline': {
            'scope': 'shipment',
            'events': timeline_events,
            'append_only': True,
            'authority': 'action_log',
        },
        'actions_fired_count': actions_fired_count,
        'history_projection_version': str(
            getattr(settings, 'MOBILE_HISTORY_PROJECTION_VERSION', '1')
        ),
    }
