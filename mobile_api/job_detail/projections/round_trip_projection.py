"""
mobile_api/job_detail/projections/round_trip_projection.py

``round_trip`` section — booking legs, execution stage, driver-scoped progression.

Uses ``booking_selection_policy`` (shared progression rules, not dashboard selectors).
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.projections.shipment_projection import (
    build_active_shipment_slice,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from tenant_workspace.models import TenantShipment

_EMPTY_ROUND_TRIP: dict[str, Any] = {
    'booking_id': '',
    'booking_no': '',
    'trip_type': '',
    'booking_execution_stage': '',
    'progression_mode': '',
    'legs': [],
    'current_leg': {},
    'active_leg_for_driver': {},
    'next_executable_leg': {},
    'outbound_progression': {},
    'backload_progression': {},
}


def build_round_trip_section(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Booking-centric round-trip context for the Job Detail shipment leg.

    Empty-move jobs return ``{}``.
    """
    _ = request
    if context.job_type != 'shipment':
        return {}
    booking = context.booking
    shipment = context.shipment
    if booking is None or shipment is None:
        return dict(_EMPTY_ROUND_TRIP)

    shipments = _load_countable_shipments(booking)
    ordered = booking_policy.sorted_countable_shipments(shipments)
    stage = booking_policy.derive_booking_execution_stage(
        booking,
        ordered,
        driver=context.driver,
    )

    next_executable = booking_policy.get_next_executable_shipment(booking, ordered)
    active_for_driver = booking_policy.get_active_shipment_for_driver(
        context.driver,
        booking,
        ordered,
    )

    progression_mode = _progression_mode(booking)
    outbound_prog = _segment_progression(
        ordered,
        segment='outbound',
        driver=context.driver,
        booking=booking,
    )
    backload_prog = _segment_progression(
        ordered,
        segment='backload',
        driver=context.driver,
        booking=booking,
    )

    legs = [
        _leg_projection(
            leg,
            booking=booking,
            driver=context.driver,
            is_current=leg.pk == shipment.pk,
        )
        for leg in ordered
    ]

    return {
        'booking_id': str(getattr(booking, 'booking_id', None) or booking.pk or ''),
        'booking_no': str(getattr(booking, 'booking_no', '') or ''),
        'trip_type': booking_policy.normalized_trip_type(booking),
        'booking_execution_stage': stage,
        'progression_mode': progression_mode,
        'legs': legs,
        'current_leg': _leg_projection(
            shipment,
            booking=booking,
            driver=context.driver,
            is_current=True,
        ),
        'active_leg_for_driver': _leg_projection(
            active_for_driver,
            booking=booking,
            driver=context.driver,
        )
        if active_for_driver
        else {},
        'next_executable_leg': _leg_projection(
            next_executable,
            booking=booking,
            driver=context.driver,
        )
        if next_executable
        else {},
        'outbound_progression': outbound_prog,
        'backload_progression': backload_prog,
    }


def _load_countable_shipments(booking: Any) -> list[Any]:
    from mobile_api.job_detail.helpers.booking_job_context import load_booking_shipments

    return load_booking_shipments(booking)


def _progression_mode(booking: Any) -> str:
    assigned = getattr(booking, 'assigned_driver_id', None)
    backload = getattr(booking, 'booking_line_backload_driver_id', None)
    if assigned and backload and assigned != backload:
        return 'split_driver'
    return 'same_driver'


def _norm_line(value: str | None) -> str:
    return (value or '').strip().casefold()


def _segment_progression(
    shipments: list[Any],
    *,
    segment: str,
    driver: Any,
    booking: Any,
) -> dict[str, Any]:
    """Outbound or backload segment summary for round-trip UIs."""
    if segment == 'outbound':
        legs = [
            s
            for s in shipments
            if _norm_line(getattr(s, 'booking_item_type', None)) == 'outbound'
        ]
    else:
        legs = [
            s
            for s in shipments
            if _norm_line(getattr(s, 'booking_item_type', None)) in {'backload', 'inbound'}
        ]

    total = len(legs)
    exec_done = sum(
        1 for s in legs if booking_policy.is_shipment_execution_complete(s)
    )
    driver_legs = [
        s for s in legs if booking_policy.driver_owns_shipment_leg(driver, booking, s)
    ]

    active = None
    for s in legs:
        if not booking_policy.is_shipment_execution_complete(s):
            active = s
            break

    return {
        'legs_total': total,
        'legs_execution_completed': exec_done,
        'driver_owns_any_leg': bool(driver_legs),
        'driver_owns_leg_ids': [
            str(getattr(s, 'shipment_id', None) or s.pk or '') for s in driver_legs
        ],
        'active_leg': _leg_projection(
            active,
            booking=booking,
            driver=driver,
        )
        if active
        else {},
        'all_execution_complete': total > 0 and exec_done == total,
    }


def _leg_projection(
    shipment: Any | None,
    *,
    booking: Any,
    driver: Any,
    is_current: bool = False,
) -> dict[str, Any]:
    if shipment is None:
        return {}
    base = build_active_shipment_slice(shipment)
    base['execution_complete'] = booking_policy.is_shipment_execution_complete(
        shipment
    )
    base['business_complete'] = booking_policy.is_shipment_business_complete(shipment)
    base['driver_owns_leg'] = booking_policy.driver_owns_shipment_leg(
        driver,
        booking,
        shipment,
    )
    base['is_current_leg'] = is_current
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    base['is_delivered'] = status in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }
    return base
