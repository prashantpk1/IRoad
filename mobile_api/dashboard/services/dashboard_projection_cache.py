"""
mobile_api/dashboard/services/dashboard_projection_cache.py

Per-request projection cache: one Action Log fetch reused across reconcile,
timeline, POD/COD compliance, and polling fingerprints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.polling_constants import DASHBOARD_ACTION_LOG_SCAN_LIMIT

from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
    scoped_preshipment_action_logs,
)
from iroad_tenants.operation_runtime.latest_action_aggregator import (
    scoped_movement_action_logs,
    scoped_shipment_action_logs,
)


@dataclass
class DashboardProjectionCache:
    """In-memory request scope — not persisted; not shared across workers."""

    shipment_logs: list[Any] = field(default_factory=list)
    movement_logs: list[Any] = field(default_factory=list)
    booking_logs: list[Any] = field(default_factory=list)
    latest_action_log_id: str = ''
    log_scan_limit: int = DASHBOARD_ACTION_LOG_SCAN_LIMIT
    queries_executed: int = 0

    def timeline_logs(self, *, scope: str) -> list[Any]:
        """Head slice for dashboard timeline (no extra ORM round-trip)."""
        if scope == 'shipment':
            source = self.shipment_logs
        elif scope == 'booking':
            source = self.booking_logs
        else:
            source = self.movement_logs
        return list(source[:5])

    def primary_logs(self) -> list[Any]:
        if self.shipment_logs:
            return self.shipment_logs
        if self.booking_logs:
            return self.booking_logs
        return self.movement_logs


def load_projection_cache(context: DriverDashboardContext) -> DashboardProjectionCache:
    """
    Load bounded Action Logs once for the active shipment or empty move.

    Attaches result to ``context.projection_cache`` and sets
    ``context.latest_action_log_id``.
    """
    existing = getattr(context, 'projection_cache', None)
    if isinstance(existing, DashboardProjectionCache):
        return existing

    cache = DashboardProjectionCache()
    driver_pk = booking_policy._driver_pk(context.driver)
    if driver_pk is None:
        context.projection_cache = cache
        return cache

    limit = DASHBOARD_ACTION_LOG_SCAN_LIMIT
    shipment = context.active_shipment
    movement = (
        context.active_empty_movement if context.active_shipment is None else None
    )

    if shipment is not None:
        qs = scoped_shipment_action_logs(
            shipment,
            movement=None,
            driver_id=driver_pk,
            scan_limit=limit,
        )
        cache.shipment_logs = list(qs)
        cache.queries_executed += 1
        if cache.shipment_logs:
            head = cache.shipment_logs[0]
            cache.latest_action_log_id = str(
                getattr(head, 'log_id', None) or getattr(head, 'pk', '') or ''
            )
    elif movement is not None:
        qs = scoped_movement_action_logs(
            movement,
            driver_id=driver_pk,
            scan_limit=limit,
        )
        cache.movement_logs = list(qs)
        cache.queries_executed += 1
        if cache.movement_logs:
            head = cache.movement_logs[0]
            cache.latest_action_log_id = str(
                getattr(head, 'log_id', None) or getattr(head, 'pk', '') or ''
            )
    elif context.active_booking is not None:
        from mobile_api.job_detail.helpers.booking_job_context import (
            resolve_booking_preshipment_item_type,
        )

        qs = scoped_preshipment_action_logs(
            context.active_booking,
            booking_item_type=resolve_booking_preshipment_item_type(
                context.active_booking,
                driver=context.driver,
            ),
            driver_id=driver_pk,
            scan_limit=limit,
        )
        cache.booking_logs = list(qs)
        cache.queries_executed += 1
        if cache.booking_logs:
            head = cache.booking_logs[0]
            cache.latest_action_log_id = str(
                getattr(head, 'log_id', None) or getattr(head, 'pk', '') or ''
            )

    context.projection_cache = cache
    context.latest_action_log_id = cache.latest_action_log_id
    return cache


def get_projection_cache(
    context: DriverDashboardContext,
) -> DashboardProjectionCache | None:
    cache = getattr(context, 'projection_cache', None)
    return cache if isinstance(cache, DashboardProjectionCache) else None
