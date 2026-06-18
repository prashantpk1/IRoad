"""
Resolve the booking line used for atomic auto-shipment birth (A4).

Ensures round-trip backload inherits per-line POD doc count, COD, truck, and
addresses from the correct leg — not the first line without an active shipment.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
    resolve_preshipment_booking_item_type,
)


def resolve_auto_shipment_target_line(
    booking: Any,
    *,
    booking_item_type_hint: str = '',
) -> dict[str, Any] | None:
    """Pick the booking line row for ``_tenant_shipment_birth_from_booking_line``."""
    if booking is None:
        return None

    from iroad_tenants.views import (
        _tenant_shipment_booking_line_rows,
        _tenant_shipment_line_has_existing_shipment,
        _tenant_shipment_match_booking_line,
    )

    leg = (booking_item_type_hint or '').strip()
    if not leg:
        leg = resolve_preshipment_booking_item_type(booking, '')

    if leg:
        matched = _tenant_shipment_match_booking_line(
            booking,
            booking_item_type=leg,
        )
        if matched is not None and not _tenant_shipment_line_has_existing_shipment(
            booking,
            matched['booking_item_type'],
        ):
            return matched

    for line in _tenant_shipment_booking_line_rows(booking):
        line_type = (line.get('booking_item_type') or '').strip()
        if leg and line_type != leg:
            continue
        if not _tenant_shipment_line_has_existing_shipment(booking, line_type):
            return line

    return None
