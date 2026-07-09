"""
mobile_api/dashboard/selectors/booking_selection_policy.py

Pure booking/shipment selection rules for the driver dashboard.

Lifecycle split (mobile execution vs portal/accounting):

- **Execution complete** — ``CLOSED``, or ``DELIVERED`` / ``POD_SUBMITTED`` only
  after POD (+ COD when applicable) gates pass; drives leg sequencing and active
  shipment for the driver.
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

_POST_DELIVERY_EXECUTION_STATUSES = frozenset(
    {
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
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


def _shipment_mobile_execution_gates_satisfied(shipment: TenantShipment | Any) -> bool:
    """POD (+ COD when applicable) done — leg may hand off to the next booking row."""
    if shipment is None:
        return False
    order_type = (getattr(shipment, 'order_type', None) or '').strip().upper()
    if order_type == 'COD':
        if (
            getattr(shipment, 'collection_status', None)
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return False
    pod_status = (getattr(shipment, 'pod_status', None) or '').strip()
    if pod_status == TenantShipment.PodStatus.COMPLETED:
        return True
    try:
        from iroad_tenants.operation_runtime.side_effects import (
            _mobile_pod_compliance_satisfied,
        )

        return _mobile_pod_compliance_satisfied(shipment)
    except Exception:
        return False


def is_shipment_execution_complete(shipment: TenantShipment | Any) -> bool:
    """
    Leg finished for mobile execution sequencing.

    ``CLOSED`` always completes. ``DELIVERED`` / ``POD_SUBMITTED`` complete only
    when POD (+ COD) gates pass so round-trip leg 2 cannot start after
    Unloading Completed (OA-0008) before POD (OA-0009).
    """
    status = _norm_status(shipment)
    if status == TenantShipment.ShipmentStatus.CLOSED:
        return True
    if status not in _POST_DELIVERY_EXECUTION_STATUSES:
        return False
    return _shipment_mobile_execution_gates_satisfied(shipment)


def is_shipment_business_complete(shipment: TenantShipment | Any) -> bool:
    """Leg finalized for portal/accounting — ``CLOSED`` only."""
    return _norm_status(shipment) == TenantShipment.ShipmentStatus.CLOSED


def is_shipment_completed(shipment: TenantShipment | Any) -> bool:
    """Backward-compatible alias — business complete (``CLOSED``)."""
    return is_shipment_business_complete(shipment)


def is_booking_cancelled(booking: TenantBooking | Any) -> bool:
    return (booking.booking_status or '').strip() == TenantBooking.Status.CANCELLED


def is_booking_operationally_cancelled(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any] | None = None,
) -> bool:
    """
    Booking must not drive mobile jobs when portal shows it as Cancelled.

    Covers R3 (stored Cancelled), derived header Cancelled (all legs cancelled),
    and Confirmed headers whose only shipment rows are Cancelled.
    """
    if booking is None:
        return True
    if is_booking_cancelled(booking):
        return True
    try:
        from iroad_tenants.booking_status import (
            BOOKING_HEADER_CANCELLED,
            derive_booking_header_status,
        )

        if derive_booking_header_status(booking) == BOOKING_HEADER_CANCELLED:
            return True
    except Exception:
        pass
    if shipments is not None:
        rows = list(shipments)
        if rows and not countable_shipments(rows):
            # Backload row existed but is cancelled — booking is fully dead.
            if any(_is_secondary_line_type(s) for s in rows):
                return True
            if is_backload_leg_pending(booking, rows):
                return False
            return True
    return False


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


def _is_outbound_line_type(shipment: TenantShipment | Any) -> bool:
    line = _norm_line_type(getattr(shipment, 'booking_item_type', None))
    if line in {'backload', 'inbound'}:
        return False
    return line == 'outbound' or line == ''


def round_trip_defers_job_close(
    booking: TenantBooking | Any | None,
    shipment: TenantShipment | Any | None = None,
    *,
    shipments: Sequence[TenantShipment | Any] | None = None,
) -> bool:
    """
    Round-trip bookings defer Job Close on outbound only until POD/COD are done.

    After outbound POD (+ COD) the driver must tap **End Job** on the timeline to
    finish round 1 explicitly, then continue the return leg — avoids mixing round 1
    and round 2 state on one screen.
    """
    if booking is None:
        return False
    if normalized_trip_type(booking).casefold() != 'round':
        return False

    rows = list(shipments) if shipments is not None else []
    if not rows:
        try:
            manager = getattr(booking, 'shipments', None)
            if manager is not None:
                rows = list(countable_shipments(manager.all()))
        except Exception:
            rows = []

    if is_booking_fully_complete(rows, booking=booking):
        return False
    if shipment is None:
        return True
    if _is_outbound_line_type(shipment):
        from iroad_tenants.operation_execution import (
            _shipment_leg_pod_cod_complete_for_job_close,
        )

        if _shipment_leg_pod_cod_complete_for_job_close(shipment):
            return False
        return True
    if _is_secondary_line_type(shipment):
        nxt = get_next_executable_shipment(booking, rows)
        if nxt is None:
            return False
        return getattr(nxt, 'pk', None) != getattr(shipment, 'pk', None)
    return True


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
    """Progress by execution-complete legs (POD/COD gates + ``CLOSED``)."""
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


def _outbound_shipments_all(shipments: Sequence[TenantShipment | Any]) -> list[Any]:
    return [
        s
        for s in (shipments or [])
        if _norm_line_type(getattr(s, 'booking_item_type', None)) == 'outbound'
    ]


def _outbound_primary_resolved(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> bool:
    """
    Outbound leg is finished for backload handoff (execution-complete or cancelled).

    Used when cancelled outbound rows are excluded from countable legs but backload
  is still Confirmed with no shipment row yet.
    """
    if normalized_trip_type(booking).casefold() != 'round':
        return False
    outbound_rows = _outbound_shipments_all(shipments)
    if not outbound_rows:
        return False
    return all(
        is_shipment_cancelled(s) or is_shipment_execution_complete(s)
        for s in outbound_rows
    )


def is_backload_leg_pending(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> bool:
    """
    Round-trip backload is planned but no shipment row exists yet.

    Matches portal booking line ``Planned`` after outbound is executed/closed,
    or after outbound shipment was cancelled (R1) while backload stays Confirmed.
    """
    if normalized_trip_type(booking).casefold() != 'round':
        return False
    if _has_backload_shipment_row(shipments):
        return False
    legs = _countable_sorted(shipments)
    primary, _ = _round_trip_primary_secondary_segments(legs)
    if not primary:
        return _outbound_primary_resolved(booking, shipments)
    return all(
        is_shipment_business_complete(s) or is_shipment_cancelled(s)
        for s in primary
    )


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


def _leg_has_blocking_driver_work(shipment: TenantShipment | Any) -> bool:
    """Leg still needs driver steps (movement, POD/COD, or End Job)."""
    if is_shipment_cancelled(shipment):
        return False
    if not is_shipment_execution_complete(shipment):
        return True
    return not is_shipment_business_complete(shipment)


def get_next_executable_shipment(
    booking: TenantBooking | Any,
    shipments: Sequence[TenantShipment | Any],
) -> Any | None:
    """
    First leg that still needs driver work, in deterministic order.

    Round-trip: a backload/inbound leg is never next until every prior leg is
    business-closed (End Job). Outbound may stay ``Delivered`` after POD/COD
    until the driver closes round 1 explicitly.
    """
    ordered = _countable_sorted(shipments)
    is_round = normalized_trip_type(booking).casefold() == 'round'
    for index, shipment in enumerate(ordered):
        if is_round and index > 0:
            priors = ordered[:index]
            if any(
                not is_shipment_business_complete(prior)
                and not is_shipment_cancelled(prior)
                for prior in priors
            ):
                continue
        if _leg_has_blocking_driver_work(shipment):
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
    At most one active focus shipment for this driver on this booking.

    Uses **booking-wide blocking** for execution sequencing: the next
    execution-incomplete leg must be owned by this driver. When that leg is
    already ``DELIVERED`` / ``CLOSED`` but the booking is still open (COD,
    job close, portal finalization), return the driver's latest leg that is not
    yet business-complete (``CLOSED``).
    """
    next_executable = get_next_executable_shipment(booking, shipments)
    if next_executable is not None:
        if driver_owns_shipment_leg(driver, booking, next_executable):
            return next_executable
        return None

    ordered = _countable_sorted(shipments)
    for shipment in reversed(ordered):
        if not driver_owns_shipment_leg(driver, booking, shipment):
            continue
        if not is_shipment_business_complete(shipment):
            return shipment
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
        if (
            normalized_trip_type(booking).casefold() == 'round'
            and is_backload_leg_pending(booking, shipments)
        ):
            return BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED
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

    if is_round and is_backload_leg_pending(booking, shipments):
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
    if is_booking_operationally_cancelled(booking, shipments):
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
