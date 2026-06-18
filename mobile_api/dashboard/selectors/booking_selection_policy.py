"""
mobile_api/dashboard/selectors/booking_selection_policy.py

Pure booking/shipment selection rules for the driver dashboard.

Lifecycle split (mobile execution vs portal/accounting):

- **Execution complete** — ``DELIVERED`` or ``CLOSED``; drives leg sequencing,
  next executable shipment, and active shipment for the driver.
- **Business complete** — ``CLOSED`` only; drives booking fully-complete skip
  and business progress percentages.

``BOOKING_EXECUTION_STAGE`` is derived from sorted countable legs + execution
flags (minimal status use only to distinguish backload *queued* vs *active*).

Reuses terminal-status semantics from ``iroad_tenants.operation_runtime``.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from tenant_workspace.models import TenantBooking, TenantShipment

from iroad_tenants.operation_runtime.shipment_execution_stage import (
    _TERMINAL_SHIPMENT_STATUSES,
)

# Leg execution order for round-trip and one-way bookings.
_LINE_TYPE_ORDER: dict[str, int] = {
    'outbound': 0,
    'inbound': 1,
    'backload': 2,
}

_EXECUTION_COMPLETE_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }
)

# Incomplete legs still in yard / not yet on road (stage discrimination only).
_PRE_ROAD_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.LOADED,
    }
)

# --- BOOKING_EXECUTION_STAGE (API contract) ---
BOOKING_EXECUTION_STAGE_NOT_STARTED = 'NOT_STARTED'
BOOKING_EXECUTION_STAGE_PARTIAL = 'PARTIAL'
BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED = 'OUTBOUND_COMPLETED'
BOOKING_EXECUTION_STAGE_BACKLOAD_ACTIVE = 'BACKLOAD_ACTIVE'
BOOKING_EXECUTION_STAGE_EXECUTION_COMPLETED = 'EXECUTION_COMPLETED'
BOOKING_EXECUTION_STAGE_BUSINESS_COMPLETED = 'BUSINESS_COMPLETED'


def _norm_line_type(value: str | None) -> str:
    return (value or '').strip().casefold()


def _norm_status(shipment: TenantShipment | Any) -> str:
    return (getattr(shipment, 'shipment_status', None) or '').strip()


def is_shipment_cancelled(shipment: TenantShipment | Any) -> bool:
    return _norm_status(shipment) == TenantShipment.ShipmentStatus.CANCELLED


def is_shipment_execution_complete(shipment: TenantShipment | Any) -> bool:
    """
    Leg finished for mobile execution sequencing.

    ``DELIVERED`` or ``CLOSED`` — next leg may become executable without waiting
    for portal ``CLOSED`` finalization on the prior leg.
    """
    return _norm_status(shipment) in _EXECUTION_COMPLETE_STATUSES


def is_shipment_business_complete(shipment: TenantShipment | Any) -> bool:
    """Leg finalized for portal/accounting — ``CLOSED`` only."""
    return _norm_status(shipment) == TenantShipment.ShipmentStatus.CLOSED


def is_shipment_completed(shipment: TenantShipment | Any) -> bool:
    """Backward-compatible alias — business complete (``CLOSED``)."""
    return is_shipment_business_complete(shipment)


def is_booking_cancelled(booking: TenantBooking | Any) -> bool:
    return (booking.booking_status or '').strip() == TenantBooking.Status.CANCELLED


def is_booking_active(booking: TenantBooking | Any) -> bool:
    return (booking.booking_status or '').strip() == TenantBooking.Status.CONFIRMED


def countable_shipments(shipments: Iterable[TenantShipment | Any]) -> list[Any]:
    """Non-cancelled shipments used for totals and completion."""
    return [s for s in shipments if not is_shipment_cancelled(s)]


def shipment_sort_key(shipment: TenantShipment | Any) -> tuple:
    """Stable leg order: sequence, then Outbound → Inbound → Backload."""
    line_rank = _LINE_TYPE_ORDER.get(_norm_line_type(shipment.booking_item_type), 99)
    return (
        int(getattr(shipment, 'shipment_sequence', 0) or 0),
        line_rank,
        str(getattr(shipment, 'shipment_no', '') or ''),
    )


def sorted_shipments(shipments: Iterable[TenantShipment | Any]) -> list[Any]:
    return sorted(shipments, key=shipment_sort_key)


def _countable_sorted(shipments: Sequence[TenantShipment | Any]) -> list[Any]:
    """Deterministic leg list for sequencing (cancelled excluded, stable order)."""
    return sorted_shipments(countable_shipments(shipments))


def _is_secondary_line_type(shipment: TenantShipment | Any) -> bool:
    return _norm_line_type(getattr(shipment, 'booking_item_type', None)) in {
        'backload',
        'inbound',
    }


def _round_trip_primary_secondary_segments(
    legs: Sequence[Any],
) -> tuple[list[Any], list[Any]]:
    """
    Split sorted countable legs into (primary, secondary) for round-trip rules.

    Primary = legs before the first backload/inbound in sort order.
    Secondary = from first backload/inbound onward (may be empty).
    """
    for i, s in enumerate(legs):
        if _is_secondary_line_type(s):
            return list(legs[:i]), list(legs[i:])
    return list(legs), []


def _progress_tuple(
    shipments: Sequence[TenantShipment | Any],
    *,
    complete_fn,
) -> tuple[int, int, int]:
    """``(total, completed_count, progress_percentage)`` for one completion rule."""
    active = countable_shipments(shipments)
    total = len(active)
    if total == 0:
        return 0, 0, 0
    completed = sum(1 for s in active if complete_fn(s))
    percentage = int(round((completed / total) * 100))
    return total, completed, percentage


def booking_execution_progress(
    shipments: Sequence[TenantShipment | Any],
) -> tuple[int, int, int]:
    """Progress by execution-complete legs (``DELIVERED`` / ``CLOSED``)."""
    return _progress_tuple(
        shipments,
        complete_fn=is_shipment_execution_complete,
    )


def booking_business_progress(
    shipments: Sequence[TenantShipment | Any],
) -> tuple[int, int, int]:
    """Progress by business-complete legs (``CLOSED`` only)."""
    return _progress_tuple(
        shipments,
        complete_fn=is_shipment_business_complete,
    )


def booking_progress(
    shipments: Sequence[TenantShipment | Any],
) -> tuple[int, int, int]:
    """
    Returns execution progress ``(total, completed, progress_percentage)``.

    Prefer ``booking_execution_progress`` / ``booking_business_progress`` when
    both metrics are needed.
    """
    return booking_execution_progress(shipments)


def round_trip_expected_leg_count(booking: TenantBooking | Any) -> int:
    """Countable legs for progress UI (Round = outbound + backload)."""
    if normalized_trip_type(booking).casefold() == 'round':
        return 2
    return 1


def _has_backload_shipment_row(shipments: Sequence[TenantShipment | Any]) -> bool:
    return any(
        _is_secondary_line_type(s) for s in countable_shipments(shipments)
    )


def is_backload_leg_pending(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> bool:
    """
    Round-trip backload is planned but no shipment row exists yet.

    Matches portal booking line ``Planned`` after outbound is executed/closed.
    """
    if normalized_trip_type(booking).casefold() != 'round':
        return False
    if _has_backload_shipment_row(shipments):
        return False
    legs = _countable_sorted(shipments)
    primary, _ = _round_trip_primary_secondary_segments(legs)
    if not primary:
        return False
    return all(is_shipment_execution_complete(s) for s in primary)


def driver_owns_backload_leg(
    driver: Any,
    booking: TenantBooking | Any,
) -> bool:
    """Whether this driver is assigned to execute the backload leg."""
    driver_pk = _driver_pk(driver)
    if driver_pk is None:
        return False
    backload_driver_id = getattr(booking, 'booking_line_backload_driver_id', None)
    if backload_driver_id:
        return backload_driver_id == driver_pk
    return getattr(booking, 'assigned_driver_id', None) == driver_pk


def is_round_trip_backload_bootstrap(
    driver: Any,
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> bool:
    """Driver may start backload via booking-scoped workflow (pre-A4 birth)."""
    return is_backload_leg_pending(booking, shipments) and driver_owns_backload_leg(
        driver,
        booking,
    )


def booking_execution_progress_for_dashboard(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> tuple[int, int, int]:
    """
    Execution progress including planned round-trip legs not yet born.

    Without this, a closed outbound-only row reports 1/1 (100%) instead of 1/2.
    """
    ordered = _countable_sorted(shipments)
    total, completed, percentage = booking_execution_progress(ordered)
    expected = round_trip_expected_leg_count(booking)
    if expected > total:
        total = expected
        percentage = int(round((completed / total) * 100)) if total else 0
    return total, completed, percentage


def booking_business_progress_for_dashboard(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> tuple[int, int, int]:
    """Business progress with planned round-trip leg denominator."""
    ordered = _countable_sorted(shipments)
    total, completed, percentage = booking_business_progress(ordered)
    expected = round_trip_expected_leg_count(booking)
    if expected > total:
        total = expected
        percentage = int(round((completed / total) * 100)) if total else 0
    return total, completed, percentage


def should_display_backload_route(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
    *,
    active: Any | None = None,
    booking_stage: str = '',
) -> bool:
    """True when dashboard/job UI should show the return leg (Makkah → Jeddah)."""
    if normalized_trip_type(booking).casefold() != 'round':
        return False
    if active is not None and _is_secondary_line_type(active):
        return True
    if is_backload_leg_pending(booking, shipments):
        return True
    if (booking_stage or '').strip() == BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED:
        return True
    return pending_executable_booking_item_type(booking, shipments).casefold() == 'backload'


def pending_executable_booking_item_type(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> str:
    """Next leg label when shipment row may not exist yet (e.g. Backload)."""
    nxt = get_next_executable_shipment(booking, shipments)
    if nxt is not None:
        return str(getattr(nxt, 'booking_item_type', '') or '').strip()
    if is_backload_leg_pending(booking, shipments):
        return 'Backload'
    return ''


def is_booking_fully_complete(
    shipments: Sequence[TenantShipment | Any],
    *,
    booking: TenantBooking | Any | None = None,
) -> bool:
    """
    Booking is done when every non-cancelled shipment is business-complete (CLOSED).

    When there are no non-cancelled shipments, the booking is not treated as
    complete (still a planned/confirmed header without executable legs).

    Round trips with a pending backload leg (no active backload shipment) stay
    open even when outbound is CLOSED.
    """
    active = countable_shipments(shipments)
    if not active:
        return False
    if booking is not None:
        expected = round_trip_expected_leg_count(booking)
        if len(active) < expected:
            return False
    return all(is_shipment_business_complete(s) for s in active)


def is_booking_execution_fully_complete(
    shipments: Sequence[TenantShipment | Any],
    *,
    booking: TenantBooking | Any | None = None,
) -> bool:
    """All countable legs are execution-complete (``DELIVERED`` / ``CLOSED``)."""
    active = countable_shipments(shipments)
    if not active:
        return False
    if booking is not None:
        expected = round_trip_expected_leg_count(booking)
        if len(active) < expected:
            return False
    return all(is_shipment_execution_complete(s) for s in active)


def get_next_executable_shipment(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> Any | None:
    """
    First execution-incomplete leg in deterministic order (cancelled skipped).

    Round-trip: a backload/inbound leg is never next until every leg before it
    in sort order is execution-complete (blocking by ordering, not ad-hoc status).
    """
    _ = booking
    for shipment in _countable_sorted(shipments):
        if not is_shipment_execution_complete(shipment):
            return shipment
    return None


def driver_owns_shipment_leg(
    driver: Any,
    booking: TenantBooking | Any,
    shipment: TenantShipment | Any,
) -> bool:
    """Whether this driver is assigned to execute the shipment leg."""
    driver_pk = _driver_pk(driver)
    if driver_pk is None:
        return False

    shipment_driver_id = getattr(shipment, 'driver_id', None)
    if shipment_driver_id and shipment_driver_id == driver_pk:
        return True

    line = _norm_line_type(shipment.booking_item_type)
    if line in {'backload', 'inbound'}:
        return getattr(booking, 'booking_line_backload_driver_id', None) == driver_pk

    return getattr(booking, 'assigned_driver_id', None) == driver_pk


def get_active_shipment_for_driver(
    driver: Any,
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> Any | None:
    """
    At most one active executable shipment for this driver on this booking.

    Uses **booking-wide blocking**: the only executable focus is
    ``get_next_executable_shipment`` (deterministic order). This driver sees an
    active leg **only** when they own that next leg — so split-driver round trips
    stay isolated (e.g. backload driver gets ``None`` until outbound is
    execution-complete and the next leg is theirs).
    """
    next_executable = get_next_executable_shipment(booking, shipments)
    if next_executable is None:
        return None
    if driver_owns_shipment_leg(driver, booking, next_executable):
        return next_executable
    return None


def sorted_countable_shipments(
    shipments: Sequence[TenantShipment | Any],
) -> list[Any]:
    """Cancel-free, deterministically ordered legs for dashboard selection."""
    return _countable_sorted(shipments)


def derive_booking_execution_stage(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
    driver: Any | None = None,
) -> str:
    """
    Derived booking execution lifecycle stage (read-only).

    Based on sorted countable legs, execution/business completion, and (for
    round trips) a small status check on the next secondary leg to distinguish
    ``OUTBOUND_COMPLETED`` (backload queued) from ``BACKLOAD_ACTIVE`` (backload
    on the road). ``driver`` is accepted for API symmetry; it is not used yet.
    """
    legs = _countable_sorted(shipments)
    if not legs:
        return BOOKING_EXECUTION_STAGE_NOT_STARTED

    if is_booking_fully_complete(shipments, booking=booking):
        return BOOKING_EXECUTION_STAGE_BUSINESS_COMPLETED

    if is_booking_execution_fully_complete(shipments, booking=booking):
        return BOOKING_EXECUTION_STAGE_EXECUTION_COMPLETED

    is_round = normalized_trip_type(booking).casefold() == 'round'
    primary, secondary = _round_trip_primary_secondary_segments(legs)

    if is_round and secondary:
        primary_all_exec = all(
            is_shipment_execution_complete(s) for s in primary
        ) or not primary
        secondary_incomplete = any(
            not is_shipment_execution_complete(s) for s in secondary
        )
        if primary_all_exec and secondary_incomplete:
            next_ex = get_next_executable_shipment(booking, shipments)
            if next_ex is not None and _is_secondary_line_type(next_ex):
                if _norm_status(next_ex) in _PRE_ROAD_STATUSES:
                    return BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED
                return BOOKING_EXECUTION_STAGE_BACKLOAD_ACTIVE

    if is_round and is_backload_leg_pending(booking, legs):
        return BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED

    # NOT_STARTED: no execution-complete leg yet; every incomplete leg pre-road.
    any_exec_done = any(is_shipment_execution_complete(s) for s in legs)
    if not any_exec_done:
        incomplete = [s for s in legs if not is_shipment_execution_complete(s)]
        if incomplete and all(_norm_status(s) in _PRE_ROAD_STATUSES for s in incomplete):
            return BOOKING_EXECUTION_STAGE_NOT_STARTED

    _ = driver  # reserved for future driver-scoped stage refinements
    return BOOKING_EXECUTION_STAGE_PARTIAL


def driver_has_booking_assignment(driver: Any, booking: TenantBooking | Any) -> bool:
    driver_pk = _driver_pk(driver)
    if driver_pk is None:
        return False
    if getattr(booking, 'assigned_driver_id', None) == driver_pk:
        return True
    if getattr(booking, 'booking_line_backload_driver_id', None) == driver_pk:
        return True
    return False


def booking_is_visible_to_driver(
    driver: Any,
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> bool:
    """Driver may see this booking if assigned on header or any shipment leg."""
    if not is_booking_active(booking) or is_booking_cancelled(booking):
        return False
    if driver_has_booking_assignment(driver, booking):
        return True
    driver_pk = _driver_pk(driver)
    if driver_pk is None:
        return False
    return any(getattr(s, 'driver_id', None) == driver_pk for s in shipments)


def _driver_pk(driver: Any) -> Any:
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)


def normalized_trip_type(booking: TenantBooking | Any) -> str:
    """Expose trip type for API (Round, One-Way, etc.)."""
    return (getattr(booking, 'trip_type', None) or '').strip()


def is_terminal_shipment_status(status: str) -> bool:
    """Re-export terminal check for tests (CLOSED / CANCELLED)."""
    return (status or '').strip() in _TERMINAL_SHIPMENT_STATUSES
