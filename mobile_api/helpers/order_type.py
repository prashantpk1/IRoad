"""
mobile_api/helpers/order_type.py

Normalize booking/shipment order type for mobile read APIs.
"""
from __future__ import annotations

from typing import Any

ORDER_TYPE_COD = 'COD'
ORDER_TYPE_CREDIT = 'Credit'


def resolve_order_type_text(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
) -> str:
    """
    Return ``COD`` or ``Credit`` for driver-facing payloads.

    Shipment ``order_type`` wins; falls back to booking. Any value other than
    COD (case-insensitive) is returned as Credit.
    """
    raw = ''
    if shipment is not None:
        raw = (getattr(shipment, 'order_type', None) or '').strip()
    if not raw and booking is not None:
        raw = (getattr(booking, 'order_type', None) or '').strip()
    if raw.upper() == ORDER_TYPE_COD:
        return ORDER_TYPE_COD
    return ORDER_TYPE_CREDIT
