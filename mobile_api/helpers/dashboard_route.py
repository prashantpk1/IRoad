"""
mobile_api/helpers/dashboard_route.py

Lightweight route summary for dashboard snapshots (no portal route engine).
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.i18n import get_localized_value


def _address_label(address, request) -> str:
    if address is None:
        return ''
    return get_localized_value(
        request,
        getattr(address, 'english_label', None) or getattr(address, 'display_name', ''),
        getattr(address, 'arabic_label', None) or getattr(address, 'display_name', ''),
    ).strip()


def build_shipment_route_summary(shipment, request=None) -> dict[str, str]:
    """
    Return ``summary`` plus optional ``from_label`` / ``to_label`` for mobile UI.
    """
    route_display = (getattr(shipment, 'route_display', None) or '').strip()
    loading = getattr(shipment, 'loading_address', None)
    delivery = getattr(shipment, 'delivery_address', None)
    from_label = _address_label(loading, request)
    to_label = _address_label(delivery, request)

    if route_display:
        summary = route_display
    elif from_label and to_label:
        summary = f'{from_label} → {to_label}'
    else:
        summary = from_label or to_label or ''

    return {
        'summary': summary,
        'from_label': from_label,
        'to_label': to_label,
    }
