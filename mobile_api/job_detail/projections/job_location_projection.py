"""
mobile_api/job_detail/projections/job_location_projection.py

Route and address blocks for the Job Detail ``job`` section (read-only).
"""
from __future__ import annotations

import re
from typing import Any, Literal

from django.db.utils import OperationalError, ProgrammingError

# Combined route labels: "Delhi — Goa", "Delhi → Goa", "Delhi - Goa"
_ROUTE_LABEL_SPLIT_RE = re.compile(r'\s*[—–\-→>]+\s*', re.UNICODE)


def _localized_label(request: Any | None, english: str, arabic: str) -> str:
    if request is not None:
        try:
            from mobile_api.helpers.i18n import get_localized_value

            return get_localized_value(request, english, arabic) or english
        except Exception:
            pass
    return english or arabic


def serialize_address(
    address: Any | None,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Map ``TenantAddressMaster`` to a mobile-friendly address DTO."""
    if address is None:
        return {}
    english = (
        getattr(address, 'english_label', '')
        or getattr(address, 'display_name', '')
        or ''
    ).strip()
    arabic = (getattr(address, 'arabic_label', '') or '').strip()
    return {
        'address_id': str(
            getattr(address, 'address_id', None) or getattr(address, 'pk', '') or ''
        ),
        'address_code': str(getattr(address, 'address_code', '') or ''),
        'display_name': str(getattr(address, 'display_name', '') or ''),
        'label': _localized_label(request, english, arabic),
        'address_category': str(getattr(address, 'address_category', '') or ''),
        'address_line_1': str(getattr(address, 'address_line_1', '') or ''),
        'address_line_2': str(getattr(address, 'address_line_2', '') or ''),
        'city': str(getattr(address, 'city', '') or ''),
        'province': str(getattr(address, 'province', '') or ''),
        'district': str(getattr(address, 'district', '') or ''),
        'street': str(getattr(address, 'street', '') or ''),
        'building_no': str(getattr(address, 'building_no', '') or ''),
        'postal_code': str(getattr(address, 'postal_code', '') or ''),
        'map_link': str(getattr(address, 'map_link', '') or ''),
        'contact_name': str(getattr(address, 'contact_name', '') or ''),
        'mobile_no_1': str(getattr(address, 'mobile_no_1', '') or ''),
        'mobile_no_2': str(getattr(address, 'mobile_no_2', '') or ''),
        'site_instructions': str(getattr(address, 'site_instructions', '') or ''),
    }


def _location_display_name(
    location: Any | None,
    *,
    request: Any | None = None,
) -> str:
    """Human-readable endpoint name from ``TenantLocationMaster``."""
    if location is None:
        return ''
    english = (getattr(location, 'location_name_english', '') or '').strip()
    arabic = (getattr(location, 'location_name_arabic', '') or '').strip()
    display = (getattr(location, 'display_label', '') or english or '').strip()
    return _localized_label(request, english or display, arabic) or display


def _split_combined_route_label(text: str) -> tuple[str, str]:
    """Parse ``route_display`` / ``route_label`` into start and end when FKs are missing."""
    combined = (text or '').strip()
    if not combined:
        return '', ''
    parts = _ROUTE_LABEL_SPLIT_RE.split(combined, maxsplit=1)
    if len(parts) == 2:
        start, end = parts[0].strip(), parts[1].strip()
        if start and end:
            return start, end
    return combined, ''


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


def serialize_route(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Route summary for shipment jobs (booking route FK + display strings)."""
    route = getattr(booking, 'route', None) if booking is not None else None
    origin = getattr(route, 'origin_point', None) if route is not None else None
    destination = (
        getattr(route, 'destination_point', None) if route is not None else None
    )
    route_label = (getattr(route, 'route_label', '') or '').strip() if route else ''

    route_display_start = ''
    route_display_end = ''
    if origin is not None and destination is not None:
        route_display_start = _location_display_name(origin, request=request)
        route_display_end = _location_display_name(destination, request=request)

    route_display = ''
    if shipment is not None:
        route_display = (getattr(shipment, 'route_display', '') or '').strip()
    if not route_display and booking is not None:
        route_display = (getattr(booking, 'route_display', '') or '').strip()
    if (
        not route_display
        and route_display_start
        and route_display_end
    ):
        route_display = f'{route_display_start} → {route_display_end}'
    if not route_display and route_label:
        route_display = route_label
    if not route_display_start and not route_display_end:
        route_display_start, route_display_end = _split_combined_route_label(
            route_display or route_label,
        )

    out: dict[str, Any] = {
        'route_display': route_display,
        'route_display_start': route_display_start,
        'route_display_end': route_display_end,
        'route_direction': '',
    }
    if booking is not None:
        out['route_direction'] = (getattr(booking, 'route_direction', '') or '').strip()
    if route is not None:
        out.update(
            {
                'route_id': str(
                    getattr(route, 'route_id', None) or getattr(route, 'pk', '') or ''
                ),
                'route_code': str(getattr(route, 'route_code', '') or ''),
                'route_label': route_label,
                'route_type': str(getattr(route, 'route_type', '') or ''),
            },
        )
    return out


def build_shipment_location_block(
    shipment: Any,
    *,
    booking: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Pickup (loading), drop (delivery), and route for a shipment job."""
    booking = booking or getattr(shipment, 'booking', None)
    pickup = (
        getattr(shipment, 'loading_address', None)
        or (getattr(booking, 'loading_address', None) if booking else None)
    )
    drop = (
        getattr(shipment, 'delivery_address', None)
        or (getattr(booking, 'delivery_address', None) if booking else None)
    )
    return {
        'route': serialize_route(
            shipment=shipment,
            booking=booking,
            request=request,
        ),
        'pickup_address': serialize_address(pickup, request=request),
        'drop_address': serialize_address(drop, request=request),
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
