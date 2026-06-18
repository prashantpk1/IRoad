"""
Shared route/address serialization for dashboard and job detail (no job_detail imports).
"""
from __future__ import annotations

import re
from typing import Any

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
    if location is None:
        return ''
    english = (getattr(location, 'location_name_english', '') or '').strip()
    arabic = (getattr(location, 'location_name_arabic', '') or '').strip()
    display = (getattr(location, 'display_label', '') or english or '').strip()
    return _localized_label(request, english or display, arabic) or display


def _split_combined_route_label(text: str) -> tuple[str, str]:
    combined = (text or '').strip()
    if not combined:
        return '', ''
    parts = _ROUTE_LABEL_SPLIT_RE.split(combined, maxsplit=1)
    if len(parts) == 2:
        start, end = parts[0].strip(), parts[1].strip()
        if start and end:
            return start, end
    return combined, ''


def serialize_route(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Route summary for shipment/booking jobs (booking route FK + display strings)."""
    route = getattr(booking, 'route', None) if booking is not None else None
    origin = getattr(route, 'origin_point', None) if route is not None else None
    destination = (
        getattr(route, 'destination_point', None) if route is not None else None
    )
    route_label = (getattr(route, 'route_label', '') or '').strip() if route else ''

    route_direction = ''
    if booking is not None:
        route_direction = (getattr(booking, 'route_direction', '') or '').strip()
    line_type = ''
    if shipment is not None:
        line_type = (getattr(shipment, 'booking_item_type', None) or '').strip().casefold()
        if line_type in {'backload', 'inbound'}:
            route_direction = 'reverse'

    fk_resolved = False
    if route_direction.casefold() == 'reverse' and origin is not None and destination is not None:
        origin, destination = destination, origin

    route_display_start = ''
    route_display_end = ''
    if origin is not None and destination is not None:
        fk_resolved = True
        route_display_start = _location_display_name(origin, request=request)
        route_display_end = _location_display_name(destination, request=request)

    route_display = ''
    if fk_resolved and route_display_start and route_display_end:
        route_display = f'{route_display_start} → {route_display_end}'
    else:
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
        elif route_display and (not route_display_start or not route_display_end):
            parsed_start, parsed_end = _split_combined_route_label(route_display)
            if parsed_start:
                route_display_start = parsed_start
            if parsed_end:
                route_display_end = parsed_end
            if route_direction.casefold() == 'reverse' and route_display_start and route_display_end:
                route_display = f'{route_display_start} → {route_display_end}'
    if not route_display_start and not route_display_end:
        route_display_start, route_display_end = _split_combined_route_label(
            route_display or route_label,
        )
        if route_direction.casefold() == 'reverse' and route_display_start and route_display_end:
            route_display = f'{route_display_start} → {route_display_end}'

    out: dict[str, Any] = {
        'route_display': route_display,
        'route_display_start': route_display_start,
        'route_display_end': route_display_end,
        'route_direction': route_direction,
    }
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
