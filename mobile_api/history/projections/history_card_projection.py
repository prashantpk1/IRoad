"""
mobile_api/history/projections/history_card_projection.py

History list card — matches driver app History tab (§14.7.1).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.history.selectors.order_type_resolver import resolve_order_type
from tenant_workspace.models import TenantShipment
from tenant_workspace.ops_display import (
    address_city_label,
    address_label,
    resolve_shipment_truck,
    truck_display_block,
)


def _norm_line(value: str | None) -> str:
    return (value or '').strip().casefold()


def _client_name(shipment: Any, booking: Any | None) -> str:
    client = getattr(shipment, 'client_account', None)
    if client is not None:
        return str(
            getattr(client, 'display_name', '')
            or getattr(client, 'name_english', '')
            or ''
        ).strip()
    if booking is not None:
        client = getattr(booking, 'client_account', None)
        if client is not None:
            return str(
                getattr(client, 'display_name', '')
                or getattr(client, 'name_english', '')
                or ''
            ).strip()
    return ''


def _address_city(address: Any | None) -> str:
    return address_city_label(address)


def _address_full(address: Any | None) -> str:
    if address is None:
        return ''
    label = address_label(address)
    if label:
        return label
    parts = [
        getattr(address, 'display_name', '') or '',
        getattr(address, 'address_line_1', '') or '',
        getattr(address, 'district', '') or '',
        getattr(address, 'city', '') or '',
    ]
    return ', '.join(part.strip() for part in parts if str(part).strip())


def resolve_history_route(
    shipment: Any,
    booking: Any | None = None,
    *,
    request: Any | None = None,
) -> dict[str, str]:
    """From/to labels and mobile route block — leg-aware (matches Job Detail)."""
    booking_obj = booking if booking is not None else getattr(shipment, 'booking', None)
    from mobile_api.job_detail.projections.job_location_projection import (
        build_shipment_location_block,
    )

    location_block = build_shipment_location_block(
        shipment,
        booking=booking_obj,
        request=request,
    )
    route = dict(location_block.get('route') or {})
    pickup = dict(location_block.get('pickup_address') or {})
    drop = dict(location_block.get('drop_address') or {})

    from_label = (
        pickup.get('label')
        or pickup.get('display_name')
        or ''
    ).strip()
    to_label = (
        drop.get('label')
        or drop.get('display_name')
        or ''
    ).strip()
    origin_city = (pickup.get('city') or '').strip()
    destination_city = (drop.get('city') or '').strip()

    route_display_start = (route.get('route_display_start') or '').strip()
    route_display_end = (route.get('route_display_end') or '').strip()
    route_display = (route.get('route_display') or '').strip()

    if origin_city and destination_city:
        route_display_start = origin_city
        route_display_end = destination_city
        route_display = f'{origin_city} → {destination_city}'
    elif not route_display and route_display_start and route_display_end:
        route_display = f'{route_display_start} → {route_display_end}'

    if not from_label and route_display_start:
        from_label = route_display_start
    if not to_label and route_display_end:
        to_label = route_display_end
    if not origin_city:
        origin_city = route_display_start
    if not destination_city:
        destination_city = route_display_end

    return {
        'route_display': route_display,
        'route_display_start': route_display_start,
        'route_display_end': route_display_end,
        'route_direction': str(route.get('route_direction') or ''),
        'route_id': str(route.get('route_id') or ''),
        'route_code': str(route.get('route_code') or ''),
        'route_label': str(route.get('route_label') or route_display),
        'route_type': str(route.get('route_type') or ''),
        'from_location': from_label,
        'to_location': to_label,
        'origin_city': origin_city,
        'destination_city': destination_city,
    }


def resolve_trip_type(booking: Any | None, shipment: Any) -> str:
    """Booking/shipment trip type for API (One-Way, Round, etc.)."""
    if booking is not None:
        return booking_policy.normalized_trip_type(booking)
    return str(getattr(shipment, 'trip_type', '') or '').strip()


def route_type_label(booking: Any | None, shipment: Any) -> str:
    """
    UI route pill: Round | Outbound | Inbound.

    Round-trip bookings surface ``Round``; otherwise leg type drives the tag.
    """
    trip = resolve_trip_type(booking, shipment)
    if trip.casefold() == 'round':
        return 'Round'

    line = _norm_line(getattr(shipment, 'booking_item_type', None))
    if line in {'inbound', 'backload'}:
        return 'Inbound'
    return 'Outbound'


def payment_method_tag(shipment: Any, booking: Any | None) -> str:
    """UI order-type pill — value from DB (shipment / booking / booking line)."""
    return resolve_order_type(shipment, booking)


def final_state_labels(shipment: Any) -> tuple[str, str]:
    """
  Display status + machine final_state.

  §14.7.1: Closed (clean) · Cancelled.
    """
    status = str(getattr(shipment, 'shipment_status', '') or '').strip()
    if status == TenantShipment.ShipmentStatus.CANCELLED:
        return 'Cancelled', 'Cancelled'
    if status == TenantShipment.ShipmentStatus.CLOSED:
        return 'Completed', 'Closed'
    return 'Completed', status or 'Closed'


def resolve_job_date(shipment: Any, booking: Any | None) -> date | None:
    """Booking execution date (§14.7.1 Job Date), else shipment_date."""
    if booking is not None:
        execution = getattr(booking, 'execution_date', None)
        if execution is not None:
            return execution
        booking_date = getattr(booking, 'booking_date', None)
        if booking_date is not None:
            return booking_date
    return getattr(shipment, 'shipment_date', None)


def build_history_card(
    shipment: Any,
    *,
    actions_fired_count: int = 0,
    request: Any | None = None,
) -> dict[str, Any]:
    """Map one terminal shipment to a History list card."""
    booking = getattr(shipment, 'booking', None)
    route = resolve_history_route(shipment, booking, request=request)

    display_status, final_state = final_state_labels(shipment)
    job_date = resolve_job_date(shipment, booking)
    shipment_date = getattr(shipment, 'shipment_date', None)
    order_type = resolve_order_type(shipment, booking)

    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)

    return {
        'shipment_id': str(shipment_id) if shipment_id is not None else '',
        'shipment_no': str(getattr(shipment, 'shipment_no', '') or ''),
        'booking_id': str(booking_id) if booking_id is not None else '',
        'booking_no': str(getattr(booking, 'booking_no', '') or '') if booking else '',
        'trip_type': resolve_trip_type(booking, shipment),
        'status': display_status,
        'final_state': final_state,
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
        'truck': truck_display_block(resolve_shipment_truck(shipment, booking)),
        'order_type': order_type,
        'payment_method': order_type,
        'transaction_type': order_type,
        'client_name': _client_name(shipment, booking),
        'job_date': job_date.isoformat() if job_date else '',
        'shipment_date': shipment_date.isoformat() if shipment_date else '',
        'actions_fired_count': int(actions_fired_count or 0),
        'read_only': True,
    }
