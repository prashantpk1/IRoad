"""
Booking-scoped Job Detail helpers (round-trip backload bootstrap).
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
    outbound_execution_complete_anchor,
)
from iroad_tenants.operation_runtime.impacts import operation_action_matches
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_loading_action,
    is_pickup_action,
)
from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.helpers.route_backload_proxy import backload_route_booking_proxy
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext


def load_booking_shipments(booking: Any) -> list[Any]:
    if booking is None:
        return []
    if hasattr(booking, 'shipments'):
        try:
            return list(booking.shipments.all())
        except Exception:
            pass
    return list(getattr(booking, 'shipments', []) or [])


def resolve_pending_booking_item_type(
    booking: Any,
    *,
    driver: Any | None = None,
) -> str:
    """Next executable leg type for booking-scoped workflow/execute (e.g. Backload)."""
    _ = driver
    if booking is None:
        return ''
    shipments = policy.sorted_countable_shipments(load_booking_shipments(booking))
    if policy.is_backload_leg_pending(booking, shipments):
        return 'Backload'
    booking_item_type = policy.pending_executable_booking_item_type(booking, shipments)
    if not booking_item_type:
        booking_item_type = 'Outbound'
    return str(booking_item_type or '').strip()


def leg_is_backload_for_addresses(exec_ctx: dict[str, Any]) -> bool:
    """Whether pickup/drop should use the return-leg address swap."""
    if exec_ctx.get('backload_bootstrap'):
        return True
    bit = (exec_ctx.get('booking_item_type') or '').strip().casefold()
    if bit in {'backload', 'inbound'}:
        return True
    stage = (exec_ctx.get('booking_execution_stage') or '').strip()
    if stage == policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED:
        return True
    return bool(exec_ctx.get('show_backload_route'))


def resolve_booking_job_execution_context(context: JobDetailContext) -> dict[str, Any]:
    """Shared leg flags for booking job projections."""
    booking = context.booking
    if booking is None:
        return {
            'shipments': [],
            'booking_execution_stage': '',
            'backload_bootstrap': False,
            'show_backload_route': False,
            'booking_item_type': '',
            'route_booking': None,
        }

    shipments = policy.sorted_countable_shipments(load_booking_shipments(booking))
    stage = policy.derive_booking_execution_stage(
        booking,
        shipments,
        driver=context.driver,
    )
    backload_bootstrap = policy.is_backload_leg_pending(booking, shipments)
    show_backload_route = policy.should_display_backload_route(
        booking,
        shipments,
        booking_stage=stage,
    )
    booking_item_type = resolve_pending_booking_item_type(
        booking,
        driver=context.driver,
    )

    route_booking = booking
    if show_backload_route:
        route_booking = backload_route_booking_proxy(booking)

    return {
        'shipments': shipments,
        'booking_execution_stage': stage,
        'backload_bootstrap': backload_bootstrap,
        'show_backload_route': show_backload_route,
        'booking_item_type': booking_item_type,
        'route_booking': route_booking,
    }


def is_booking_preshipment_action(action: Any) -> bool:
    if action is None:
        return False
    if operation_action_matches(action, 'start job', 'a1', 'action 1'):
        return True
    if is_pickup_action(action) or is_loading_action(action):
        return True
    if bool(getattr(action, 'auto_shipment_post', False)):
        return True
    code = (getattr(action, 'action_code', '') or '').strip().upper()
    return code in {'A1', 'A2', 'A3', 'A4'}


def filter_booking_timeline_logs(
    logs: list[Any],
    *,
    booking: Any,
    backload_bootstrap: bool,
) -> list[Any]:
    """Booking job timelines use preshipment logs only."""
    scoped = [
        log
        for log in logs
        if not getattr(log, 'shipment_id', None)
    ]
    if not backload_bootstrap:
        return scoped

    anchor = outbound_execution_complete_anchor(booking)
    if anchor is None:
        return []

    filtered: list[Any] = []
    for log in scoped:
        log_date = getattr(log, 'log_date', None)
        if log_date is None:
            continue
        if log_date > anchor:
            filtered.append(log)
    return filtered
