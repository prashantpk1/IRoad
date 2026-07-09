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
    from mobile_api.job_detail.helpers.booking_job_context import (
        load_booking_shipments_for_policy,
    )

    return load_booking_shipments_for_policy(booking)


def _norm_line_type(value: str | None) -> str:
    return (value or '').strip().casefold()


def _is_primary_outbound_shipment(shipment: Any | None) -> bool:
    """Outbound leg — explicit ``Outbound`` or legacy empty line type."""
    if shipment is None:
        return False
    line = _norm_line_type(getattr(shipment, 'booking_item_type', None))
    return line not in {'backload', 'inbound'}


def backload_preshipment_pending_on_booking(
    *,
    driver: Any,
    booking: Any,
    shipments: list[Any] | None = None,
) -> bool:
    """
    Return leg still runs A1–A4 on ``job_type=booking`` (no active movement yet).

    Covers backload bootstrap (no row) and a born ``Created`` backload row before
    Confirm Loaded / movement birth.
    """
    if booking is None or driver is None:
        return False
    if not policy.driver_owns_backload_leg(driver, booking):
        return False
    rows = shipments if shipments is not None else _load_booking_shipments(booking)
    if policy.is_backload_leg_pending(booking, rows):
        return True
    nxt = policy.get_next_executable_shipment(booking, rows)
    if nxt is None:
        return False
    line = _norm_line_type(getattr(nxt, 'booking_item_type', None))
    if line not in {'backload', 'inbound'}:
        return False
    status = (getattr(nxt, 'shipment_status', None) or '').strip()
    from tenant_workspace.models import TenantShipment

    if status not in {
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.LOADED,
    }:
        return False
    from iroad_tenants.operation_execution import _shipment_has_active_movement

    return not _shipment_has_active_movement(nxt)


def _ensure_booking_on_shipment(shipment: Any | None) -> Any | None:
    if shipment is None:
        return None
    booking = getattr(shipment, 'booking', None)
    if booking is not None:
        return booking
    booking_id = getattr(shipment, 'booking_id', None)
    if not booking_id:
        return None
    from tenant_workspace.models import TenantBooking

    return TenantBooking.objects.filter(pk=booking_id).first()


def _open_secondary_leg_for_driver(
    driver: Any,
    booking: Any,
    shipments: list[Any],
) -> Any | None:
    """Latest open backload/inbound leg owned by this driver (round-trip leg 2)."""
    from mobile_api.dashboard.selectors.booking_selection_policy import (
        sorted_countable_shipments,
    )

    for shipment in reversed(sorted_countable_shipments(shipments)):
        line = _norm_line_type(getattr(shipment, 'booking_item_type', None))
        if line not in {'backload', 'inbound'}:
            continue
        if policy.is_shipment_cancelled(shipment):
            continue
        if policy.is_shipment_business_complete(shipment):
            continue
        if not policy.driver_owns_shipment_leg(driver, booking, shipment):
            continue
        return shipment
    return None


def _outbound_leg_handoff_complete(shipment: Any) -> bool:
    """Outbound finished enough for leg-2 work (POD Submitted / Delivered / Closed)."""
    if policy.is_shipment_business_complete(shipment):
        return True
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    from tenant_workspace.models import TenantShipment

    return status in {
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }


def coerce_driver_active_shipment_leg(
    driver: Any,
    shipment: Any | None,
) -> Any | None:
    """
    Replace a stale completed primary outbound with the driver's active leg.

    Mobile may still pass round-1 ``shipment_id`` during round-2 Hard POD.
    """
    if shipment is None or driver is None:
        return shipment
    booking = _ensure_booking_on_shipment(shipment)
    if booking is None:
        return shipment
    shipments = _load_booking_shipments(booking)

    if _is_primary_outbound_shipment(shipment) and _outbound_leg_handoff_complete(shipment):
        secondary = _open_secondary_leg_for_driver(driver, booking, shipments)
        if secondary is not None:
            ship_pk = str(
                getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
            ).strip()
            secondary_pk = str(
                getattr(secondary, 'shipment_id', None) or getattr(secondary, 'pk', None) or ''
            ).strip()
            if ship_pk and secondary_pk and ship_pk != secondary_pk:
                return secondary

    if not _is_primary_outbound_shipment(shipment):
        return shipment
    active = policy.get_active_shipment_for_driver(driver, booking, shipments)
    if active is None:
        return shipment
    ship_pk = str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()
    active_pk = str(
        getattr(active, 'shipment_id', None) or getattr(active, 'pk', None) or ''
    ).strip()
    if not ship_pk or not active_pk or ship_pk == active_pk:
        return shipment
    active_line = _norm_line_type(getattr(active, 'booking_item_type', None))
    if active_line in {'backload', 'inbound'}:
        return active
    if (
        policy.is_shipment_execution_complete(shipment)
        or policy.is_shipment_cancelled(shipment)
    ):
        return active
    return shipment


def ensure_active_round_trip_scope(context: Any) -> bool:
    """
    Pivot execute/job context off a closed outbound leg when return work is open.
    """
    if context.driver is None or context.booking is None or context.shipment is None:
        return False
    shipment = context.shipment
    if not _is_primary_outbound_shipment(shipment):
        return False
    if not (
        policy.is_shipment_business_complete(shipment)
        or policy.is_shipment_cancelled(shipment)
    ):
        return False
    original_pk = str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()
    if pivot_context_to_backload_booking(
        driver=context.driver,
        booking=context.booking,
        shipment=shipment,
        context=context,
    ):
        return True
    if pivot_closed_shipment_to_active_leg(
        driver=context.driver,
        booking=context.booking,
        shipment=shipment,
        context=context,
    ):
        current_pk = str(
            getattr(context.shipment, 'shipment_id', None)
            or getattr(context.shipment, 'pk', None)
            or ''
        ).strip()
        return bool(current_pk and current_pk != original_pk)
    return False


def should_pivot_shipment_to_backload_booking(
    *,
    driver: Any,
    booking: Any | None,
    shipment: Any | None,
) -> bool:
    """True when shipment job detail/execute should use booking backload bootstrap."""
    if booking is None or shipment is None or driver is None:
        return False
    if not _is_primary_outbound_shipment(shipment):
        return False
    if not (
        policy.is_shipment_cancelled(shipment)
        or policy.is_shipment_business_complete(shipment)
    ):
        return False
    shipments = _load_booking_shipments(booking)
    return backload_preshipment_pending_on_booking(
        driver=driver,
        booking=booking,
        shipments=shipments,
    )


def _reset_projection_cache(context: Any) -> None:
    cache = getattr(context, '_execution_projection_cache', None)
    if cache is not None and hasattr(cache, 'reset_job_detail_scope'):
        cache.reset_job_detail_scope()
    if hasattr(context, 'projection_cache'):
        context.projection_cache = None


def should_pivot_closed_shipment_to_active_leg(
    *,
    driver: Any,
    booking: Any | None,
    shipment: Any | None,
) -> bool:
    """True when opening a finished leg should follow the driver's current leg."""
    if booking is None or shipment is None or driver is None:
        return False
    if not policy.is_shipment_business_complete(shipment):
        return False
    shipments = _load_booking_shipments(booking)
    if backload_preshipment_pending_on_booking(
        driver=driver,
        booking=booking,
        shipments=shipments,
    ):
        return False
    active = policy.get_active_shipment_for_driver(driver, booking, shipments)
    if active is None:
        return False
    ship_id = str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()
    active_id = str(
        getattr(active, 'shipment_id', None) or getattr(active, 'pk', None) or ''
    ).strip()
    return bool(ship_id and active_id and ship_id != active_id)


def pivot_closed_shipment_to_active_leg(
    *,
    driver: Any,
    booking: Any,
    shipment: Any,
    context: Any,
) -> bool:
    """
    Redirect stale closed-leg job detail to the driver's active shipment leg.

    Covers round-trip leg 2 when the backload shipment row already exists.
    """
    if not should_pivot_closed_shipment_to_active_leg(
        driver=driver,
        booking=booking,
        shipment=shipment,
    ):
        return False

    shipments = _load_booking_shipments(booking)
    active = policy.get_active_shipment_for_driver(driver, booking, shipments)
    if active is None:
        return False

    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)
    active_id = getattr(active, 'shipment_id', None) or getattr(active, 'pk', None)

    context.job_type = 'shipment'
    context.job_id = str(active_id) if active_id is not None else ''
    context.shipment = active
    context.booking = booking

    meta = dict(getattr(context, 'resolver_meta', None) or {})
    meta['closed_shipment_active_leg_redirect'] = True
    meta['redirected_from_shipment_id'] = (
        str(shipment_id) if shipment_id is not None else ''
    )
    meta['redirected_from_job_type'] = 'shipment'
    context.resolver_meta = meta

    _reset_projection_cache(context)
    return True


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
    if backload_preshipment_pending_on_booking(
        driver=driver,
        booking=booking,
        shipments=shipments,
    ):
        return False
    from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
        is_backload_preshipment_cycle,
        resolve_preshipment_booking_item_type,
    )
    from iroad_tenants.operation_execution import _shipment_has_active_movement

    active = policy.get_active_shipment_for_driver(driver, booking, shipments)
    if active is not None:
        line = _norm_line_type(getattr(active, 'booking_item_type', None))
        if line in {'backload', 'inbound'} and not _shipment_has_active_movement(active):
            return False
        return True
    item_type = resolve_preshipment_booking_item_type(booking, '')
    if is_backload_preshipment_cycle(booking, item_type):
        nxt = policy.get_next_executable_shipment(booking, shipments)
        line = _norm_line_type(getattr(nxt, 'booking_item_type', None) if nxt else '')
        if nxt is not None and line in {'backload', 'inbound'}:
            if not _shipment_has_active_movement(nxt):
                return False
    return False


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

    _reset_projection_cache(context)

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

    _reset_projection_cache(context)

    return True
