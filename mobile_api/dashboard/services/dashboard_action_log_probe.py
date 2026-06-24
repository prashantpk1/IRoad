"""
mobile_api/dashboard/services/dashboard_action_log_probe.py

Latest Action Log id for dashboard fingerprints (uses projection cache when loaded).
"""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantOperationActionLog

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.services.dashboard_projection_cache import (
    get_projection_cache,
    load_projection_cache,
)


def fetch_latest_action_log_id(
    context: DriverDashboardContext,
    *,
    driver_pk: Any | None = None,
) -> str:
    """
    Latest log id for active shipment or empty-move scope.

    Prefer ``load_projection_cache`` (single scan); this helper falls back to one
    query only when the cache was not loaded yet.
    """
    cache = get_projection_cache(context)
    if cache is not None:
        return (cache.latest_action_log_id or '').strip()

    driver_pk = driver_pk or booking_policy._driver_pk(context.driver)
    if driver_pk is None:
        return ''

    shipment = context.active_shipment
    movement = (
        context.active_empty_movement if context.active_shipment is None else None
    )

    if shipment is not None:
        log_id = (
            TenantOperationActionLog.objects.filter(
                shipment_id=shipment.pk,
                driver_id=driver_pk,
            )
            .exclude(operation_action__isnull=True)
            .order_by('-log_date', '-created_at', '-log_id')
            .values_list('log_id', flat=True)
            .first()
        )
        return str(log_id or '')

    if movement is not None:
        log_id = (
            TenantOperationActionLog.objects.filter(
                truck_movement_id=movement.pk,
                driver_id=driver_pk,
            )
            .exclude(operation_action__isnull=True)
            .order_by('-log_date', '-created_at', '-log_id')
            .values_list('log_id', flat=True)
            .first()
        )
        return str(log_id or '')

    booking = context.active_booking
    if booking is not None and shipment is None and movement is None:
        from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
            scoped_preshipment_action_logs,
        )
        from mobile_api.job_detail.helpers.booking_job_context import (
            resolve_booking_preshipment_item_type,
        )

        log_id = (
            scoped_preshipment_action_logs(
                booking,
                booking_item_type=resolve_booking_preshipment_item_type(
                    booking,
                    driver=context.driver,
                ),
                driver_id=driver_pk,
                scan_limit=1,
            )
            .values_list('log_id', flat=True)
            .first()
        )
        return str(log_id or '')

    return ''


def ensure_latest_action_log_id(context: DriverDashboardContext) -> str:
    """Load projection cache if needed and return latest log id."""
    cache = get_projection_cache(context)
    if cache is None:
        cache = load_projection_cache(context)
    return (cache.latest_action_log_id or '').strip()
