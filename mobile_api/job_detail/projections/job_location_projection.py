"""
mobile_api/job_detail/projections/job_location_projection.py

Route and address blocks for the Job Detail ``job`` section (read-only).
"""
from __future__ import annotations

from typing import Any, Literal

from django.db.utils import OperationalError, ProgrammingError

from mobile_api.helpers.booking_endpoint_addresses import resolve_leg_endpoint_addresses
from mobile_api.helpers.job_location_serialization import (
    serialize_address,
    serialize_route,
)

__all__ = [
    'build_movement_location_block',
    'build_shipment_location_block',
    'serialize_address',
    'serialize_location_point',
    'serialize_route',
]


def _localized_label(request: Any | None, english: str, arabic: str) -> str:
    if request is not None:
        try:
            from mobile_api.helpers.i18n import get_localized_value

            return get_localized_value(request, english, arabic) or english
        except Exception:
            pass
    return english or arabic


def _movement_location_point(
    movement: Any,
    side: Literal['from', 'to'],
) -> Any | None:
    """
    Resolve movement from/to location without raising when the tenant schema
    has no ``tenant_location_master`` table (stale FK ids still on the row).
    """
    field = f'{side}_location_point'
    fk_id = getattr(movement, f'{field}_id', None)
    if not fk_id:
        return None
    cache = movement._state.fields_cache
    if field in cache:
        return cache[field]
    try:
        from tenant_workspace.models import TenantLocationMaster

        location = TenantLocationMaster.objects.filter(pk=fk_id).first()
    except (ProgrammingError, OperationalError):
        location = None
    cache[field] = location
    return location


def serialize_location_point(
    location: Any | None,
    *,
    request: Any | None = None,
    map_link: str = '',
) -> dict[str, Any]:
    """Map ``TenantLocationMaster`` (empty-move from/to) to address-like DTO."""
    if location is None:
        if not (map_link or '').strip():
            return {}
        return {'map_link': (map_link or '').strip()}
    english = (getattr(location, 'location_name_english', '') or '').strip()
    arabic = (getattr(location, 'location_name_arabic', '') or '').strip()
    display = (getattr(location, 'display_label', '') or english or '').strip()
    return {
        'location_id': str(
            getattr(location, 'location_id', None) or getattr(location, 'pk', '') or ''
        ),
        'location_code': str(getattr(location, 'location_code', '') or ''),
        'display_name': display,
        'label': _localized_label(request, english or display, arabic),
        'province': str(getattr(location, 'province', '') or ''),
        'map_link': (map_link or '').strip(),
    }


def build_shipment_location_block(
    shipment: Any,
    *,
    booking: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Pickup (loading), drop (delivery), and route for a shipment job."""
    booking = booking or getattr(shipment, 'booking', None)
    line_type = str(getattr(shipment, 'booking_item_type', '') or '').strip()
    trip = (getattr(booking, 'trip_type', None) or '').strip().casefold() if booking else ''

    if booking is not None and trip == 'round' and getattr(booking, 'route', None) is not None:
        pickup_address, drop_address = resolve_leg_endpoint_addresses(
            booking,
            booking_item_type=line_type,
            request=request,
        )
    else:
        pickup = (
            getattr(shipment, 'loading_address', None)
            or (getattr(booking, 'loading_address', None) if booking else None)
        )
        drop = (
            getattr(shipment, 'delivery_address', None)
            or (getattr(booking, 'delivery_address', None) if booking else None)
        )
        pickup_address = serialize_address(pickup, request=request)
        drop_address = serialize_address(drop, request=request)

    return {
        'route': serialize_route(
            shipment=shipment,
            booking=booking,
            request=request,
        ),
        'pickup_address': pickup_address,
        'drop_address': drop_address,
    }


def build_movement_location_block(
    movement: Any,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """From/to locations for movement jobs; falls back to linked shipment addresses."""
    shipment = getattr(movement, 'shipment', None)
    if shipment is not None:
        block = build_shipment_location_block(
            shipment,
            booking=getattr(movement, 'booking', None) or getattr(shipment, 'booking', None),
            request=request,
        )
        block['movement_from'] = serialize_location_point(
            _movement_location_point(movement, 'from'),
            request=request,
            map_link=getattr(movement, 'from_location_map_link', '') or '',
        )
        block['movement_to'] = serialize_location_point(
            _movement_location_point(movement, 'to'),
            request=request,
            map_link=getattr(movement, 'to_location_map_link', '') or '',
        )
        return block

    return {
        'route': {},
        'pickup_address': serialize_location_point(
            _movement_location_point(movement, 'from'),
            request=request,
            map_link=getattr(movement, 'from_location_map_link', '') or '',
        ),
        'drop_address': serialize_location_point(
            _movement_location_point(movement, 'to'),
            request=request,
            map_link=getattr(movement, 'to_location_map_link', '') or '',
        ),
    }
