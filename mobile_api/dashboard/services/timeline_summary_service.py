"""
mobile_api/dashboard/services/timeline_summary_service.py

Lightweight read-only timeline slice for the dashboard (no full timeline API).
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
)

_DASHBOARD_TIMELINE_LIMIT = 20


def build_timeline_summary(context: DriverDashboardContext) -> dict[str, Any]:
    """
    Recent-events preview — reuses ``DashboardProjectionCache`` when loaded.
    """
    driver_pk = booking_policy._driver_pk(context.driver)
    if driver_pk is None:
        return _empty_timeline()

    cache = get_projection_cache(context)
    shipment = context.active_shipment
    movement = context.active_empty_movement if shipment is None else None

    if shipment is not None:
        if cache is not None and cache.shipment_logs:
            return _format_timeline_result(
                cache.timeline_logs(scope='shipment'),
                scope='shipment',
            )
        return _timeline_for_shipment(shipment, driver_pk=driver_pk)
    if movement is not None:
        if cache is not None and cache.movement_logs:
            return _format_timeline_result(
                cache.timeline_logs(scope='movement'),
                scope='movement',
            )
        return _timeline_for_movement(movement, driver_pk=driver_pk)
    booking = context.active_booking
    if booking is not None:
        if cache is not None and cache.booking_logs:
            return _format_timeline_result(
                cache.timeline_logs(scope='booking'),
                scope='booking',
            )
        return _timeline_for_booking(booking, driver_pk=driver_pk)
    return _empty_timeline()


def _timeline_for_shipment(shipment: Any, *, driver_pk: Any) -> dict[str, Any]:
    logs = (
        TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
            driver_id=driver_pk,
        )
        .exclude(operation_action__isnull=True)
        .select_related('operation_action')
        .order_by('-log_date', '-created_at', '-log_id')[:_DASHBOARD_TIMELINE_LIMIT]
    )
    return _format_timeline_result(logs, scope='shipment')


def _timeline_for_movement(movement: Any, *, driver_pk: Any) -> dict[str, Any]:
    logs = (
        TenantOperationActionLog.objects.filter(
            truck_movement_id=movement.pk,
            driver_id=driver_pk,
        )
        .exclude(operation_action__isnull=True)
        .select_related('operation_action')
        .order_by('-log_date', '-created_at', '-log_id')[:_DASHBOARD_TIMELINE_LIMIT]
    )
    return _format_timeline_result(logs, scope='movement')


def _timeline_for_booking(booking: Any, *, driver_pk: Any) -> dict[str, Any]:
    from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
        scoped_preshipment_action_logs,
    )
    from mobile_api.job_detail.helpers.booking_job_context import (
        resolve_booking_preshipment_item_type,
    )

    logs = scoped_preshipment_action_logs(
        booking,
        booking_item_type=resolve_booking_preshipment_item_type(booking),
        driver_id=driver_pk,
        scan_limit=_DASHBOARD_TIMELINE_LIMIT,
    )
    return _format_timeline_result(logs, scope='booking')


def _format_timeline_result(logs, *, scope: str) -> dict[str, Any]:
    events = []
    for log in logs:
        action = getattr(log, 'operation_action', None)
        events.append(
            {
                'log_id': str(getattr(log, 'log_id', '') or log.pk or ''),
                'log_no': str(getattr(log, 'log_no', '') or ''),
                'log_date': _iso(getattr(log, 'log_date', None)),
                'action_code': str(getattr(action, 'action_code', '') or ''),
                'action_label': str(
                    getattr(action, 'english_label', None)
                    or getattr(action, 'action_code', '')
                    or ''
                ),
            }
        )
    return {
        'scope': scope,
        'preview_limit': _DASHBOARD_TIMELINE_LIMIT,
        'recent_count': len(events),
        'recent_events': events,
        'has_more': len(events) >= _DASHBOARD_TIMELINE_LIMIT,
    }


def _empty_timeline() -> dict[str, Any]:
    return {
        'scope': '',
        'preview_limit': _DASHBOARD_TIMELINE_LIMIT,
        'recent_count': 0,
        'recent_events': [],
        'has_more': False,
    }


def _iso(value) -> str:
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)
