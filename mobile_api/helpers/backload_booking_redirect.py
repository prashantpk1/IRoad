"""
Pivot closed outbound shipment scope to booking-scoped backload bootstrap.

When a round-trip outbound leg is execution-complete and the backload shipment
row does not exist yet, mobile must execute A1–A4 on ``job_type=booking`` — not
on the closed outbound shipment (stale timeline / wrong allowed actions).
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as policy


def _load_booking_shipments(booking: Any) -> list[Any]:
    from mobile_api.job_detail.helpers.booking_job_context import load_booking_shipments

    return load_booking_shipments(booking)


def _norm_line_type(value: str | None) -> str:
    return (value or '').strip().casefold()


def should_pivot_shipment_to_backload_booking(
    *,
    driver: Any,
    booking: Any | None,
    shipment: Any | None,
) -> bool:
    """True when shipment job detail/execute should use booking backload bootstrap."""
    if booking is None or shipment is None or driver is None:
        return False
    line = _norm_line_type(getattr(shipment, 'booking_item_type', None))
    if line in {'backload', 'inbound'}:
        return False
    shipments = _load_booking_shipments(booking)
    if not policy.is_backload_leg_pending(booking, shipments):
        return False
    if not policy.driver_owns_backload_leg(driver, booking):
        return False
    if line == 'outbound':
        if policy.is_shipment_cancelled(shipment):
            return True
        if policy.is_shipment_execution_complete(shipment):
            return True
    return False


def should_pivot_booking_to_active_shipment(
    *,
    driver: Any,
    booking: Any | None,
) -> bool:
    """
    Booking job detail/execute should follow the driver's active shipment leg.

    Skipped during backload bootstrap (booking-scoped A1–A4 for the return leg).
    """
    if booking is None or driver is None:
        return False
    shipments = _load_booking_shipments(booking)
    if policy.is_backload_leg_pending(booking, shipments):
        return False
    active = policy.get_active_shipment_for_driver(driver, booking, shipments)
    return active is not None


def pivot_booking_to_active_shipment(
    *,
    driver: Any,
    booking: Any,
    context: Any,
) -> bool:
    """
    Mutate a Job Detail or Execute context to the driver's active shipment leg.

    Prevents stale booking-scoped preshipment actions (e.g. reborn OA-0004) when
    the outbound shipment already exists and is still executable.
    """
    if not should_pivot_booking_to_active_shipment(driver=driver, booking=booking):
        return False

    shipments = _load_booking_shipments(booking)
    active = policy.get_active_shipment_for_driver(driver, booking, shipments)
    if active is None:
        return False

    shipment_id = getattr(active, 'shipment_id', None) or getattr(active, 'pk', None)
    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)

    context.job_type = 'shipment'
    context.job_id = str(shipment_id) if shipment_id is not None else ''
    context.shipment = active
    context.booking = booking

    meta = dict(getattr(context, 'resolver_meta', None) or {})
    meta['active_shipment_redirect'] = True
    meta['redirected_from_booking_id'] = (
        str(booking_id) if booking_id is not None else ''
    )
    meta['redirected_from_job_type'] = 'booking'
    context.resolver_meta = meta

    cache = getattr(context, '_execution_projection_cache', None)
    if cache is not None and hasattr(cache, 'reset_job_detail_scope'):
        cache.reset_job_detail_scope()

    return True


def pivot_context_to_backload_booking(
    *,
    driver: Any,
    booking: Any,
    shipment: Any,
    context: Any,
) -> bool:
    """
    Mutate a Job Detail or Execute context to booking-scoped backload bootstrap.

    Clears ``shipment`` so workflow/timeline use preshipment A1–A4 for Backload.
    """
    if not should_pivot_shipment_to_backload_booking(
        driver=driver,
        booking=booking,
        shipment=shipment,
    ):
        return False

    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)

    context.job_type = 'booking'
    context.job_id = str(booking_id) if booking_id is not None else ''
    context.shipment = None
    context.booking = booking

    meta = dict(getattr(context, 'resolver_meta', None) or {})
    meta['backload_booking_redirect'] = True
    meta['redirected_from_shipment_id'] = (
        str(shipment_id) if shipment_id is not None else ''
    )
    meta['redirected_from_job_type'] = 'shipment'
    context.resolver_meta = meta

    cache = getattr(context, '_execution_projection_cache', None)
    if cache is not None and hasattr(cache, 'reset_job_detail_scope'):
        cache.reset_job_detail_scope()

    return True
