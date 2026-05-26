"""
mobile_api/dashboard/projections/booking_projection.py

Pure functions: booking ORM/graph → dashboard booking card dict.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.projections.shipment_projection import (
    build_active_shipment_slice,
)
from mobile_api.dashboard.selectors import booking_selection_policy as policy


def build_booking_card(
    booking: Any,
    *,
    tenant_schema: str = '',
    driver: Any | None = None,
    selection: DriverBookingSelectionResult | None = None,
    active_shipment: Any | None = None,
    round_trip_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Map a booking (+ optional selection result) to the job card contract.

    Includes ``booking_execution_stage`` (``BOOKING_EXECUTION_STAGE_*``).
    """
    _ = (tenant_schema, round_trip_meta)
    if booking is None:
        return _empty_booking_card()

    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)

    if selection is not None:
        total = selection.shipments_total
        exec_completed = selection.shipments_execution_completed
        biz_completed = selection.shipments_business_completed
        exec_pct = selection.execution_progress_percentage
        biz_pct = selection.business_progress_percentage
        active = selection.active_shipment
        shipments = selection.shipments
        booking_stage = selection.booking_execution_stage
    else:
        shipments = list(
            booking.shipments.all()
            if hasattr(booking, 'shipments')
            else []
        )
        ordered = policy.sorted_countable_shipments(shipments)
        total, exec_completed, exec_pct = policy.booking_execution_progress(ordered)
        _, biz_completed, biz_pct = policy.booking_business_progress(ordered)
        booking_stage = policy.derive_booking_execution_stage(
            booking, ordered, driver=driver
        )
        if active_shipment is not None:
            active = active_shipment
        elif driver is not None:
            active = policy.get_active_shipment_for_driver(
                driver, booking, ordered
            )
        else:
            active = policy.get_next_executable_shipment(booking, ordered)

    meta = round_trip_meta or _round_trip_meta(booking, shipments)

    payload: dict[str, Any] = {
        'booking_id': str(booking_id) if booking_id is not None else '',
        'booking_no': str(getattr(booking, 'booking_no', '') or ''),
        'trip_type': policy.normalized_trip_type(booking),
        'shipments_total': total,
        'shipments_execution_completed': exec_completed,
        'shipments_business_completed': biz_completed,
        'shipments_completed': exec_completed,
        'active_shipment': build_active_shipment_slice(active),
        'execution_progress_percentage': exec_pct,
        'business_progress_percentage': biz_pct,
        'progress_percentage': exec_pct,
        'booking_execution_stage': booking_stage or '',
    }
    if meta:
        payload['round_trip'] = meta
    return payload


def build_booking_card_from_selection(
    selection: DriverBookingSelectionResult,
    *,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Build job card directly from ``select_current_driver_booking`` output."""
    return build_booking_card(
        selection.booking,
        tenant_schema=tenant_schema,
        selection=selection,
    )


def _round_trip_meta(
    booking: Any,
    shipments: list[Any],
) -> dict[str, Any]:
    """Next executable leg hints for round-trip UIs (read-only)."""
    if policy.normalized_trip_type(booking).casefold() != 'round':
        return {}

    next_shipment = policy.get_next_executable_shipment(booking, shipments)
    return {
        'next_executable_booking_item_type': str(
            getattr(next_shipment, 'booking_item_type', '') or ''
        )
        if next_shipment
        else '',
        'legs': ['Outbound', 'Backload'],
    }


def _empty_booking_card() -> dict[str, Any]:
    return {
        'booking_id': '',
        'booking_no': '',
        'trip_type': '',
        'shipments_total': 0,
        'shipments_execution_completed': 0,
        'shipments_business_completed': 0,
        'shipments_completed': 0,
        'active_shipment': {},
        'execution_progress_percentage': 0,
        'business_progress_percentage': 0,
        'progress_percentage': 0,
        'booking_execution_stage': '',
    }
