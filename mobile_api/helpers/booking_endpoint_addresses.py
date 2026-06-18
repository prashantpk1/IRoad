"""
Round-trip leg pickup/drop — site addresses swapped per leg (outbound + backload).

Round trips use booking loading/delivery address masters (full site names like
``Industrial City Phase 1, Jeddah``) with leg-aware swap. Route location points
are fallback when address FKs are missing.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.job_location_serialization import serialize_address


def _normalized_trip_type(booking: Any) -> str:
    return (getattr(booking, 'trip_type', None) or '').strip().casefold()


def leg_is_backload_line(booking_item_type: str | None) -> bool:
    return (booking_item_type or '').strip().casefold() in {'backload', 'inbound'}


def _serialize_route_location_points(
    booking: Any,
    *,
    leg_is_backload: bool,
    request: Any | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    route = getattr(booking, 'route', None)
    if route is None:
        return {}, {}
    from mobile_api.job_detail.projections.job_location_projection import (
        serialize_location_point,
    )

    origin = getattr(route, 'origin_point', None)
    destination = getattr(route, 'destination_point', None)
    if leg_is_backload:
        pickup_loc, drop_loc = destination, origin
    else:
        pickup_loc, drop_loc = origin, destination
    return (
        serialize_location_point(pickup_loc, request=request),
        serialize_location_point(drop_loc, request=request),
    )


def resolve_booking_endpoint_addresses(
    booking: Any,
    *,
    leg_is_backload: bool = False,
    request: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Pickup and drop DTOs for a booking-scoped job card.

    Round trip with address FKs:
      - Outbound: loading → pickup, delivery → drop (Jeddah site → Mecca site)
      - Backload: delivery → pickup, loading → drop (Mecca site → Jeddah site)
    """
    if booking is None:
        return {}, {}

    is_round = _normalized_trip_type(booking) == 'round'
    loading_addr = getattr(booking, 'loading_address', None)
    delivery_addr = getattr(booking, 'delivery_address', None)

    if is_round and (loading_addr is not None or delivery_addr is not None):
        if leg_is_backload:
            pickup_src, drop_src = delivery_addr, loading_addr
        else:
            pickup_src, drop_src = loading_addr, delivery_addr
        return (
            serialize_address(pickup_src, request=request),
            serialize_address(drop_src, request=request),
        )

    route_pickup, route_drop = _serialize_route_location_points(
        booking,
        leg_is_backload=leg_is_backload,
        request=request,
    )
    if route_pickup or route_drop:
        return route_pickup, route_drop

    if leg_is_backload:
        pickup_src, drop_src = delivery_addr, loading_addr
    else:
        pickup_src, drop_src = loading_addr, delivery_addr
    return (
        serialize_address(pickup_src, request=request),
        serialize_address(drop_src, request=request),
    )


def resolve_leg_endpoint_addresses(
    booking: Any,
    *,
    booking_item_type: str = '',
    request: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Shipment or booking leg — outbound vs backload picks endpoint order."""
    return resolve_booking_endpoint_addresses(
        booking,
        leg_is_backload=leg_is_backload_line(booking_item_type),
        request=request,
    )
