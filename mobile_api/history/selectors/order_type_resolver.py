"""
mobile_api/history/selectors/order_type_resolver.py

Resolve order type (COD / Credit) dynamically from persisted shipment data.
"""
from __future__ import annotations

from typing import Any


def resolve_order_type(shipment: Any, booking: Any | None = None) -> str:
    """
    Order type for mobile UI badges — no hardcoded mapping.

    Resolution order:
      1. ``shipment.order_type``
      2. ``booking.order_type``
      3. matched virtual booking line (same logic as portal shipment form)
    """
    if shipment is None:
        return ''

    on_shipment = str(getattr(shipment, 'order_type', None) or '').strip()
    if on_shipment:
        return on_shipment

    booking = booking if booking is not None else getattr(shipment, 'booking', None)
    if booking is None:
        return ''

    on_booking = str(getattr(booking, 'order_type', None) or '').strip()
    if on_booking:
        return on_booking

    try:
        from iroad_tenants.views import _tenant_shipment_match_booking_line

        matched = _tenant_shipment_match_booking_line(
            booking,
            booking_item=str(getattr(shipment, 'booking_item_ref', '') or ''),
            booking_item_type=str(getattr(shipment, 'booking_item_type', '') or ''),
        )
        if matched:
            return str(matched.get('order_type') or '').strip()
    except Exception:
        return ''

    return ''
