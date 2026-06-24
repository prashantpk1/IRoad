"""
mobile_api/job_detail/projections/job_location_projection.py

Route and address blocks for the Job Detail ``job`` section (read-only).
"""
from __future__ import annotations

from typing import Any, Literal

from django.db.utils import OperationalError, ProgrammingError

from mobile_api.helpers.booking_endpoint_addresses import (
    leg_is_backload_line,
    resolve_leg_endpoint_addresses,
    should_swap_leg_endpoint_addresses,
)
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
    address: str = '',
    latitude: str = '',
    longitude: str = '',
) -> dict[str, Any]:
    """Map movement endpoint to an address-like DTO (Location Master and/or Places)."""
    address_text = (address or '').strip()
    lat = str(latitude or '').strip()
    lng = str(longitude or '').strip()
    link = (map_link or '').strip()

    if location is None and not address_text and not link and not (lat and lng):
        return {}

    if not link and lat and lng:
        try:
            from iroad_tenants.fleet_gps_tracking import build_google_maps_link

            link = build_google_maps_link(lat, lng)
        except Exception:
            pass

    result: dict[str, Any] = {}
    if location is not None:
        english = (getattr(location, 'location_name_english', '') or '').strip()
        arabic = (getattr(location, 'location_name_arabic', '') or '').strip()
        display = (getattr(location, 'display_label', '') or english or '').strip()
        result = {
            'location_id': str(
                getattr(location, 'location_id', None) or getattr(location, 'pk', '') or ''
            ),
            'location_code': str(getattr(location, 'location_code', '') or ''),
            'display_name': display,
            'label': _localized_label(request, english or display, arabic),
            'province': str(getattr(location, 'province', '') or ''),
        }

    if address_text:
        result['display_name'] = address_text
        result['label'] = address_text
    elif not result:
        result['display_name'] = ''
        result['label'] = ''

    if lat:
        result['latitude'] = lat
    if lng:
        result['longitude'] = lng
    if link:
        result['map_link'] = link
    return result


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

    booking_execution_stage = ''
    show_backload_route = False
    backload_bootstrap = False
    if booking is not None:
        from mobile_api.dashboard.selectors import booking_selection_policy as policy
        from mobile_api.job_detail.helpers.booking_job_context import (
            load_booking_shipments_for_policy,
        )

        shipments_all = load_booking_shipments_for_policy(booking)
        booking_execution_stage = policy.derive_booking_execution_stage(
            booking,
            shipments_all,
        )
        show_backload_route = policy.should_display_backload_route(
            booking,
            shipments_all,
            active=shipment,
            booking_stage=booking_execution_stage,
        )
        backload_bootstrap = policy.is_backload_leg_pending(booking, shipments_all)

    swap_leg_addresses = should_swap_leg_endpoint_addresses(
        booking_item_type=line_type,
        booking_execution_stage=booking_execution_stage,
        show_backload_route=show_backload_route,
        backload_bootstrap=backload_bootstrap,
    )
    use_booking_leg_endpoints = booking is not None and (
        trip == 'round' or leg_is_backload_line(line_type) or swap_leg_addresses
    )

    if use_booking_leg_endpoints:
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


def _movement_endpoint_projection(
    movement: Any,
    side: Literal['from', 'to'],
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    prefix = f'{side}_'
    return serialize_location_point(
        _movement_location_point(movement, side),
        request=request,
        map_link=getattr(movement, f'{prefix}location_map_link', '') or '',
        address=getattr(movement, f'{prefix}location_address', '') or '',
        latitude=getattr(movement, f'{prefix}latitude', '') or '',
        longitude=getattr(movement, f'{prefix}longitude', '') or '',
    )


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
        block['movement_from'] = _movement_endpoint_projection(
            movement,
            'from',
            request=request,
        )
        block['movement_to'] = _movement_endpoint_projection(
            movement,
            'to',
            request=request,
        )
        return block

    return {
        'route': {},
        'pickup_address': _movement_endpoint_projection(movement, 'from', request=request),
        'drop_address': _movement_endpoint_projection(movement, 'to', request=request),
    }
