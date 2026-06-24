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
from mobile_api.helpers.booking_endpoint_addresses import (
    resolve_booking_endpoint_addresses,
)
from mobile_api.helpers.job_booking_meta import (
    resolve_client_name,
    resolve_execution_date,
)
from mobile_api.helpers.job_location_serialization import (
    serialize_address,
    serialize_route,
)
from mobile_api.helpers.route_backload_proxy import backload_route_booking_proxy


def build_booking_card(
    booking: Any,
    *,
    tenant_schema: str = '',
    driver: Any | None = None,
    selection: DriverBookingSelectionResult | None = None,
    active_shipment: Any | None = None,
    round_trip_meta: dict[str, Any] | None = None,
    request: Any | None = None,
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
        booking_for_route = selection.booking
    else:
        shipments = list(
            booking.shipments.all()
            if hasattr(booking, 'shipments')
            else []
        )
        ordered = policy.sorted_countable_shipments(shipments)
        total, exec_completed, exec_pct = policy.booking_execution_progress_for_dashboard(
            booking,
            ordered,
        )
        _, biz_completed, biz_pct = policy.booking_business_progress_for_dashboard(
            booking,
            ordered,
        )
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
        booking_for_route = booking

    meta = round_trip_meta or _round_trip_meta(booking_for_route, shipments)
    show_backload_route = policy.should_display_backload_route(
        booking_for_route,
        shipments,
        active=active,
        booking_stage=booking_stage or '',
    )
    route_booking = booking_for_route
    if show_backload_route and booking_for_route is not None:
        route_booking = backload_route_booking_proxy(booking_for_route)

    ordered_shipments = policy.sorted_countable_shipments(shipments)
    if selection is not None and selection.is_backload_bootstrap:
        is_backload_bootstrap = True
    else:
        is_backload_bootstrap = policy.is_backload_leg_pending(
            booking,
            shipments,
        )
        if is_backload_bootstrap and driver is not None:
            is_backload_bootstrap = policy.driver_owns_backload_leg(driver, booking)

    loading_address, delivery_address = resolve_booking_endpoint_addresses(
        booking,
        leg_is_backload=(
            is_backload_bootstrap
            or show_backload_route
            or (booking_stage or '').strip()
            == policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED
        ),
        request=request,
    )

    payload: dict[str, Any] = {
        'booking_id': str(booking_id) if booking_id is not None else '',
        'booking_no': str(getattr(booking, 'booking_no', '') or ''),
        'trip_type': policy.normalized_trip_type(booking),
        'shipments_total': total,
        'shipments_execution_completed': exec_completed,
        'shipments_business_completed': biz_completed,
        'shipments_completed': exec_completed,
        'active_shipment': build_active_shipment_slice(
            active,
            booking=booking,
            request=request,
        ),
        'route': serialize_route(
            shipment=active,
            booking=route_booking,
            request=request,
        ),
        'pickup_address': loading_address,
        'drop_address': delivery_address,
        'execution_progress_percentage': exec_pct,
        'business_progress_percentage': biz_pct,
        'progress_percentage': exec_pct,
        'booking_execution_stage': booking_stage or '',
        'client_name': resolve_client_name(booking=booking, request=request),
        'execution_date': resolve_execution_date(booking=booking),
    }
    _attach_preferred_job_pointer(
        payload,
        booking=booking,
        booking_id=booking_id,
        active=active,
        is_backload_bootstrap=is_backload_bootstrap,
    )
    if meta:
        payload['round_trip'] = meta
    return payload


def build_booking_card_from_selection(
    selection: DriverBookingSelectionResult,
    *,
    tenant_schema: str = '',
    request: Any | None = None,
) -> dict[str, Any]:
    """Build job card directly from ``select_current_driver_booking`` output."""
    return build_booking_card(
        selection.booking,
        tenant_schema=tenant_schema,
        selection=selection,
        request=request,
    )


def _round_trip_meta(
    booking: Any,
    shipments: list[Any],
) -> dict[str, Any]:
    """Next executable leg hints for round-trip UIs (read-only)."""
    if policy.normalized_trip_type(booking).casefold() != 'round':
        return {}

    ordered = policy.sorted_countable_shipments(shipments)
    next_type = policy.pending_executable_booking_item_type(booking, ordered)
    meta: dict[str, Any] = {
        'legs': ['Outbound', 'Backload'],
        'next_executable_booking_item_type': next_type or '',
    }
    if policy.is_backload_leg_pending(booking, shipments):
        meta['backload_bootstrap_pending'] = True
        meta['next_executable_booking_item_type'] = 'Backload'
    elif next_type:
        meta['next_executable_booking_item_type'] = next_type
    return meta


def _attach_preferred_job_pointer(
    payload: dict[str, Any],
    *,
    booking: Any,
    booking_id: Any,
    active: Any | None,
    is_backload_bootstrap: bool,
) -> None:
    """
    Tell mobile which job to open (booking vs shipment).

    Backload bootstrap (BA-002 Planned, no SH row) must use ``job_type=booking``.
    """
    if is_backload_bootstrap:
        payload['job_type'] = 'booking'
        payload['job_id'] = str(booking_id) if booking_id is not None else ''
        payload['job_no'] = str(getattr(booking, 'booking_no', '') or '')
        payload['booking_item_type'] = 'Backload'
        payload['backload_bootstrap_pending'] = True
        _attach_open_job_pointer(payload)
        return

    if active is not None:
        shipment_id = getattr(active, 'shipment_id', None) or getattr(active, 'pk', None)
        payload['job_type'] = 'shipment'
        payload['job_id'] = str(shipment_id) if shipment_id is not None else ''
        payload['job_no'] = str(getattr(active, 'shipment_no', '') or '')
        payload['booking_item_type'] = str(
            getattr(active, 'booking_item_type', '') or ''
        ).strip()
        _attach_open_job_pointer(payload)
        return

    payload['job_type'] = 'booking'
    payload['job_id'] = str(booking_id) if booking_id is not None else ''
    payload['job_no'] = str(getattr(booking, 'booking_no', '') or '')
    if is_backload_bootstrap:
        payload['booking_item_type'] = 'Backload'
        payload['backload_bootstrap_pending'] = True
    else:
        payload['booking_item_type'] = 'Outbound'
    _attach_open_job_pointer(payload)


def _attach_open_job_pointer(payload: dict[str, Any]) -> None:
    """Explicit target for dashboard Open Job (mirrors job_type/job_id fields)."""
    job_type = str(payload.get('job_type') or '').strip()
    job_id = str(payload.get('job_id') or '').strip()
    if not job_type or not job_id:
        return
    open_job: dict[str, Any] = {
        'job_type': job_type,
        'job_id': job_id,
        'job_no': str(payload.get('job_no') or ''),
        'booking_item_type': str(payload.get('booking_item_type') or ''),
    }
    if payload.get('backload_bootstrap_pending'):
        open_job['backload_bootstrap_pending'] = True
    payload['open_job'] = open_job


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
        'route': serialize_route(),
        'pickup_address': serialize_address(None),
        'drop_address': serialize_address(None),
        'execution_progress_percentage': 0,
        'business_progress_percentage': 0,
        'progress_percentage': 0,
        'booking_execution_stage': '',
        'client_name': '',
        'execution_date': '',
    }
