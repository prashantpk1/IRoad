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
    'build_empty_move_delivery_address',
    'build_movement_location_block',
    'build_shipment_location_block',
    'gps_empty_move_endpoint_block',
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


def _empty_move_endpoint_address_key(side: Literal['from', 'to']) -> str:
    return 'from_address' if side == 'from' else 'to_address'


def _movement_stored_address(movement: Any, side: Literal['from', 'to']) -> str:
    return str(getattr(movement, f'{side}_location_address', '') or '').strip()


def _empty_move_arrival_duplicates_departure(movement: Any) -> bool:
    """True when ``to_*`` route fields match departure — not a real End Job capture yet."""
    from iroad_tenants.operation_runtime.movement_ops import (
        empty_move_arrival_matches_departure,
    )

    return empty_move_arrival_matches_departure(movement)


def _sanitize_empty_move_arrival_block(
    movement: Any,
    block: dict[str, Any],
    *,
    log_latitude: str = '',
    log_longitude: str = '',
) -> dict[str, Any]:
    """Hide arrival text/GPS that mirrors departure until End Job captures fresh GPS."""
    if str(log_latitude or '').strip() and str(log_longitude or '').strip():
        return block
    if _empty_move_arrival_duplicates_departure(movement):
        return _empty_move_pending_arrival_shell()
    return block


def _empty_move_pending_arrival_shell() -> dict[str, Any]:
    """GPS shell for End Job — destination not captured yet."""
    return _apply_gps_capture_metadata(
        {
            'display_name': '',
            'label': '',
            'awaiting_arrival_gps': True,
        },
        gps_required=True,
    )


def _enrich_empty_move_endpoint_block(
    block: dict[str, Any],
    *,
    side: Literal['from', 'to'],
    address: str,
    latitude: str = '',
    longitude: str = '',
) -> dict[str, Any]:
    """Expose mobile ``from_address`` / ``to_address`` aliases on job detail endpoints."""
    text = (address or '').strip()
    lat = str(latitude or '').strip()
    lng = str(longitude or '').strip()
    if text:
        block[_empty_move_endpoint_address_key(side)] = text
        block['display_name'] = text
        block['label'] = text
    elif lat and lng:
        coord_label = f'{lat}, {lng}'
        block['display_name'] = coord_label
        block['label'] = coord_label
    if lat:
        block['latitude'] = lat
    if lng:
        block['longitude'] = lng
    return block


def _apply_gps_capture_metadata(
    block: dict[str, Any],
    *,
    gps_required: bool = True,
) -> dict[str, Any]:
    """Ensure mobile GPS capture screens receive consistent coordinate keys."""
    block.setdefault('latitude', '')
    block.setdefault('longitude', '')
    block['location_capture_mode'] = 'gps'
    if gps_required:
        block['gps_capture_required'] = True
    return block


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
    from iroad_tenants.operation_runtime.movement_action_validator import is_empty_movement

    if is_empty_movement(movement):
        if side == 'to':
            return _empty_move_arrival_endpoint_block(movement, request=request)
        block = gps_empty_move_endpoint_block(movement, 'from', request=request)
        if block:
            return block

    prefix = f'{side}_'
    block = serialize_location_point(
        _movement_location_point(movement, side),
        request=request,
        map_link=getattr(movement, f'{prefix}location_map_link', '') or '',
        address=_movement_stored_address(movement, side),
        latitude=getattr(movement, f'{prefix}latitude', '') or '',
        longitude=getattr(movement, f'{prefix}longitude', '') or '',
    )
    if not block:
        return {}
    return _enrich_empty_move_endpoint_block(
        block,
        side=side,
        address=_movement_stored_address(movement, side),
        latitude=str(getattr(movement, f'{prefix}latitude', '') or '').strip(),
        longitude=str(getattr(movement, f'{prefix}longitude', '') or '').strip(),
    )


def gps_empty_move_endpoint_block(
    movement: Any,
    side: Literal['from', 'to'],
    *,
    request: Any | None = None,
    log_latitude: str = '',
    log_longitude: str = '',
    address_override: str = '',
) -> dict[str, Any]:
    """
    GPS-only endpoint block for empty moves (Start Job = from, End Job = to).

    Returns ``{}`` when neither coordinates nor a stored address exist yet.
    """
    prefix = f'{side}_'
    lat = str(log_latitude or getattr(movement, f'{prefix}latitude', '') or '').strip()
    lng = str(log_longitude or getattr(movement, f'{prefix}longitude', '') or '').strip()
    address = _movement_stored_address(movement, side)
    if not address:
        address = (address_override or '').strip()
    if not (lat and lng) and not address:
        return {}

    block = serialize_location_point(
        None,
        request=request,
        map_link=getattr(movement, f'{prefix}location_map_link', '') or '',
        address=address,
        latitude=lat,
        longitude=lng,
    )
    block = _enrich_empty_move_endpoint_block(
        block,
        side=side,
        address=address,
        latitude=lat,
        longitude=lng,
    )
    block = _apply_gps_capture_metadata(block, gps_required=True)
    if side == 'to':
        return _sanitize_empty_move_arrival_block(
            movement,
            block,
            log_latitude=log_latitude,
            log_longitude=log_longitude,
        )
    return block


def _empty_move_drop_address_block(
    movement: Any,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Arrival endpoint for empty moves — always GPS-shaped for End Job capture.

    Includes ``to_address`` and ``latitude`` / ``longitude`` when stored on the TML;
    otherwise returns an empty GPS shell so mobile can bind End Job location fix.
    """
    block = gps_empty_move_endpoint_block(movement, 'to', request=request)
    if block and not block.get('awaiting_arrival_gps'):
        return block

    address = _movement_stored_address(movement, 'to')
    lat = str(getattr(movement, 'to_latitude', '') or '').strip()
    lng = str(getattr(movement, 'to_longitude', '') or '').strip()
    if address or (lat and lng):
        block = serialize_location_point(
            None,
            request=request,
            map_link=getattr(movement, 'to_location_map_link', '') or '',
            address=address,
            latitude=lat,
            longitude=lng,
        )
        block = _enrich_empty_move_endpoint_block(
            block,
            side='to',
            address=address,
            latitude=lat,
            longitude=lng,
        )
        block = _apply_gps_capture_metadata(block, gps_required=True)
        return _sanitize_empty_move_arrival_block(movement, block)

    return _empty_move_pending_arrival_shell()


def _empty_move_arrival_endpoint_block(
    movement: Any,
    *,
    request: Any | None = None,
    log_latitude: str = '',
    log_longitude: str = '',
    address_override: str = '',
) -> dict[str, Any]:
    """Arrival / delivery endpoint — stamped GPS first, then planned ``to_*`` fallback."""
    block = gps_empty_move_endpoint_block(
        movement,
        'to',
        request=request,
        log_latitude=log_latitude,
        log_longitude=log_longitude,
        address_override=address_override,
    )
    if block and not block.get('awaiting_arrival_gps'):
        return block
    return _empty_move_drop_address_block(movement, request=request)


def build_empty_move_delivery_address(
    movement: Any,
    *,
    movement_logs: list[Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Delivery destination block for empty moves after Departure is completed.

    Returns ``{}`` before the in-transit / Departure milestone is logged.
    """
    from iroad_tenants.operation_runtime.movement_action_validator import is_empty_movement
    from iroad_tenants.operation_runtime.movement_stage_derivation import (
        movement_log_milestone_flags_from_logs,
    )

    if not is_empty_movement(movement) or movement_logs is None:
        return {}
    flags = movement_log_milestone_flags_from_logs(movement_logs)
    if not flags.get('in_transit_done'):
        return {}
    return dict(
        _empty_move_arrival_endpoint_block(movement, request=request),
    )


def _gps_only_empty_move_arrival(
    movement: Any,
    endpoint: dict[str, Any],
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Empty-move arrival block with GPS keys for End Job."""
    return _empty_move_arrival_endpoint_block(movement, request=request)


def build_movement_location_block(
    movement: Any,
    *,
    request: Any | None = None,
    movement_logs: list[Any] | None = None,
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

    from iroad_tenants.operation_runtime.movement_action_validator import is_empty_movement
    from iroad_tenants.operation_runtime.movement_stage_derivation import (
        movement_log_milestone_flags_from_logs,
    )

    pickup = _movement_endpoint_projection(movement, 'from', request=request)
    drop = _movement_endpoint_projection(movement, 'to', request=request)
    delivery_address: dict[str, Any] = {}
    if is_empty_movement(movement):
        pickup = (
            gps_empty_move_endpoint_block(movement, 'from', request=request)
            or pickup
        )
        if movement_logs is not None:
            flags = movement_log_milestone_flags_from_logs(movement_logs)
            if flags.get('in_transit_done'):
                delivery_address = _empty_move_arrival_endpoint_block(
                    movement,
                    request=request,
                )
                drop = dict(delivery_address)
            else:
                drop = {}
        else:
            drop = _gps_only_empty_move_arrival(
                movement,
                drop,
                request=request,
            )
    return {
        'route': {},
        'pickup_address': pickup,
        'drop_address': drop,
        'delivery_address': delivery_address,
    }
