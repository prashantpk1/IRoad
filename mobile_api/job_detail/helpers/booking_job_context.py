"""
Booking-scoped Job Detail helpers (round-trip backload bootstrap).
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
    outbound_execution_complete_anchor,
    outbound_shipment_birth_anchor,
    resolve_preshipment_booking_item_type,
)
from iroad_tenants.operation_runtime.impacts import operation_action_matches
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_loading_action,
    is_pickup_action,
)
from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.helpers.booking_endpoint_addresses import should_swap_leg_endpoint_addresses
from mobile_api.helpers.route_backload_proxy import backload_route_booking_proxy
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext


def _coerce_shipments_attr(shipments_attr: Any) -> list[Any]:
    if shipments_attr is None:
        return []
    if isinstance(shipments_attr, (list, tuple)):
        return list(shipments_attr)
    if hasattr(shipments_attr, 'all'):
        rows = shipments_attr.all()
        if isinstance(rows, (list, tuple)):
            return list(rows)
        return list(rows)
    return list(shipments_attr)


def _query_booking_shipments(booking_id: Any) -> list[Any]:
    if not booking_id:
        return []
    from tenant_workspace.models import TenantShipment

    return list(
        TenantShipment.objects.filter(booking_id=booking_id).order_by(
            'shipment_sequence',
            'shipment_no',
        )
    )


def load_booking_shipments(booking: Any) -> list[Any]:
    if booking is None:
        return []
    if hasattr(booking, 'shipments'):
        try:
            return _coerce_shipments_attr(booking.shipments)
        except Exception:
            pass
    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    return _query_booking_shipments(booking_id)


def load_booking_shipments_for_policy(booking: Any) -> list[Any]:
    """
    Full shipment graph for execution-stage / backload policy (includes cancelled).

    Prefetch on job detail may omit cancelled rows; fall back to a fresh ORM read
  so Job Detail matches dashboard backload bootstrap detection.
    """
    from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
        _all_shipments,
    )

    if booking is None:
        return []
    prefetched = load_booking_shipments(booking)
    if prefetched:
        return prefetched
    return _all_shipments(booking)


def resolve_pending_booking_item_type(
    booking: Any,
    *,
    driver: Any | None = None,
) -> str:
    """Next executable leg type for booking-scoped workflow/execute (e.g. Backload)."""
    _ = driver
    if booking is None:
        return ''
    shipments_all = load_booking_shipments_for_policy(booking)
    if policy.is_backload_leg_pending(booking, shipments_all):
        return 'Backload'
    shipments = policy.sorted_countable_shipments(shipments_all)
    booking_item_type = policy.pending_executable_booking_item_type(booking, shipments)
    if not booking_item_type:
        booking_item_type = 'Outbound'
    return str(booking_item_type or '').strip()


def leg_is_backload_for_addresses(exec_ctx: dict[str, Any]) -> bool:
    """Whether pickup/drop should use the return-leg address swap."""
    return should_swap_leg_endpoint_addresses(
        booking_item_type=str(exec_ctx.get('booking_item_type') or ''),
        booking_execution_stage=str(exec_ctx.get('booking_execution_stage') or ''),
        show_backload_route=bool(exec_ctx.get('show_backload_route')),
        backload_bootstrap=bool(exec_ctx.get('backload_bootstrap')),
    )


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

    shipments_all = load_booking_shipments_for_policy(booking)
    shipments = policy.sorted_countable_shipments(shipments_all)
    stage = policy.derive_booking_execution_stage(
        booking,
        shipments_all,
        driver=context.driver,
    )
    backload_bootstrap = policy.is_backload_leg_pending(booking, shipments_all)
    show_backload_route = policy.should_display_backload_route(
        booking,
        shipments_all,
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


def resolve_booking_preshipment_item_type(
    booking: Any,
    *,
    driver: Any | None = None,
) -> str:
    """Leg label for booking-scoped preshipment log queries (Outbound vs Backload)."""
    shipments = load_booking_shipments_for_policy(booking)
    item_type = 'Backload'
    if policy.is_backload_leg_pending(booking, shipments):
        if driver is not None and not policy.driver_owns_backload_leg(driver, booking):
            item_type = 'Outbound'
    else:
        item_type = resolve_pending_booking_item_type(booking, driver=driver) or 'Outbound'
    return resolve_preshipment_booking_item_type(booking, item_type)


def is_booking_preshipment_action(action: Any) -> bool:
    if action is None:
        return False
    if operation_action_matches(action, 'start job', 'a1', 'action 1'):
        return True
    if is_pickup_action(action) or is_loading_action(action):
        return True
    if bool(getattr(action, 'auto_shipment_post', False)):
        return True
    return False


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

    birth_at = outbound_shipment_birth_anchor(booking)
    filtered: list[Any] = []
    for log in scoped:
        log_date = getattr(log, 'log_date', None)
        if log_date is None:
            continue
        if log_date <= anchor:
            continue
        if birth_at is not None and log_date < birth_at:
            continue
        filtered.append(log)
    return filtered
