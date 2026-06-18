"""Trip booking sell-price resolution for Round / Outbound / Inbound scenarios."""
from __future__ import annotations

from decimal import Decimal


def resolve_trip_booking_sell_price(
    *,
    overrides_bucket,
    service_sell_price,
    service_outbound_sell_price,
    service_inbound_sell_price,
    trip_type,
    route_direction,
):
    """
    Resolve trip sell price per booking scenario (PCS 3.5.1).

    - Round trip -> price-list sell price (header)
    - Outbound (forward route) -> outbound price
    - Inbound (reverse route) -> inbound price
    """
    trip_type = (trip_type or '').strip()
    direction = (route_direction or 'forward').strip().lower()
    bucket = overrides_bucket or {}

    base_sell = Decimal(service_sell_price or 0)
    outbound_base = (
        Decimal(service_outbound_sell_price)
        if service_outbound_sell_price is not None
        else base_sell
    )
    inbound_base = (
        Decimal(service_inbound_sell_price)
        if service_inbound_sell_price is not None
        else base_sell
    )

    if trip_type == 'Round':
        if bucket.get('sell'):
            return Decimal(bucket['sell'])
        return base_sell

    if direction == 'reverse':
        if bucket.get('inbound'):
            return Decimal(bucket['inbound'])
        return inbound_base

    if bucket.get('outbound'):
        return Decimal(bucket['outbound'])
    return outbound_base
