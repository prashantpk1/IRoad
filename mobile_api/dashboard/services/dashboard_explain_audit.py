"""
mobile_api/dashboard/services/dashboard_explain_audit.py

Development/ops helpers to capture ORM ``EXPLAIN`` plans for dashboard queries.
"""
from __future__ import annotations

from typing import Any

from django.db import connection


def _explain_queryset(qs) -> list[dict[str, Any]]:
    sql, params = qs.query.sql_with_params()
    vendor = connection.vendor
    if vendor == 'postgresql':
        explain_sql = f'EXPLAIN (FORMAT JSON) {sql}'
    elif vendor == 'mysql':
        explain_sql = f'EXPLAIN FORMAT=JSON {sql}'
    else:
        explain_sql = f'EXPLAIN {sql}'

    with connection.cursor() as cursor:
        cursor.execute(explain_sql, params)
        row = cursor.fetchone()
    if not row:
        return []
    plan = row[0]
    if isinstance(plan, str):
        import json

        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            return [{'raw': plan}]
    if isinstance(plan, list):
        return plan
    return [plan] if isinstance(plan, dict) else [{'raw': str(plan)}]


def explain_booking_selector_query(driver_pk: Any) -> dict[str, Any]:
    """Explain plan for bounded driver booking candidate scan."""
    from django.db.models import Prefetch, Q
    from django.db.models.functions import Coalesce

    from tenant_workspace.models import TenantBooking, TenantShipment

    from mobile_api.dashboard.polling_constants import (
        DASHBOARD_BOOKING_CANDIDATE_LIMIT,
    )
    from mobile_api.dashboard.selectors.dashboard_booking_selector import (
        _OPEN_SHIPMENT_STATUSES,
    )

    shipments_qs = TenantShipment.objects.order_by(
        'shipment_sequence',
        'created_at',
    )
    qs = (
        TenantBooking.objects.filter(
            Q(assigned_driver_id=driver_pk)
            | Q(booking_line_backload_driver_id=driver_pk)
            | Q(shipments__driver_id=driver_pk),
            booking_status=TenantBooking.Status.CONFIRMED,
        )
        .filter(shipments__shipment_status__in=_OPEN_SHIPMENT_STATUSES)
        .distinct()
        .order_by(
            'booking_date',
            Coalesce('execution_date', 'booking_date'),
            'booking_sequence',
        )
        .prefetch_related(Prefetch('shipments', queryset=shipments_qs))[
            :DASHBOARD_BOOKING_CANDIDATE_LIMIT
        ]
    )
    return {
        'query': 'booking_selector',
        'plan': _explain_queryset(qs),
    }


def explain_action_log_scope_query(
    *,
    shipment_id: Any | None = None,
    movement_id: Any | None = None,
    driver_id: Any | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from tenant_workspace.models import TenantOperationActionLog

    if shipment_id is not None:
        qs = (
            TenantOperationActionLog.objects.filter(
                shipment_id=shipment_id,
                driver_id=driver_id,
            )
            .exclude(operation_action__isnull=True)
            .select_related('operation_action')
            .order_by('-log_date', '-created_at', '-log_id')[:limit]
        )
        label = 'action_log_shipment'
    elif movement_id is not None:
        qs = (
            TenantOperationActionLog.objects.filter(
                truck_movement_id=movement_id,
                driver_id=driver_id,
            )
            .exclude(operation_action__isnull=True)
            .select_related('operation_action')
            .order_by('-log_date', '-created_at', '-log_id')[:limit]
        )
        label = 'action_log_movement'
    else:
        return {'query': 'action_log', 'plan': [], 'error': 'missing scope'}

    return {'query': label, 'plan': _explain_queryset(qs)}


def explain_movement_selector_query(driver_pk: Any) -> dict[str, Any]:
    from datetime import timedelta

    from django.utils import timezone

    from tenant_workspace.models import TenantTruckMovementLog

    from mobile_api.dashboard.polling_constants import (
        DASHBOARD_MOVEMENT_CANDIDATE_LIMIT,
        DASHBOARD_MOVEMENT_LOOKBACK_DAYS,
    )

    cutoff = timezone.now().date() - timedelta(days=DASHBOARD_MOVEMENT_LOOKBACK_DAYS)
    qs = (
        TenantTruckMovementLog.objects.filter(
            driver_id=driver_pk,
            shipment_id__isnull=True,
            movement_date__gte=cutoff,
        )
        .exclude(
            status__in=(
                TenantTruckMovementLog.Status.COMPLETED,
                TenantTruckMovementLog.Status.CANCELLED,
            ),
        )
        .exclude(movement_source__iexact='loaded')
        .order_by('movement_date', 'movement_sequence', 'created_at')[
            :DASHBOARD_MOVEMENT_CANDIDATE_LIMIT
        ]
    )
    return {'query': 'movement_selector', 'plan': _explain_queryset(qs)}


def audit_dashboard_query_plans(
    *,
    driver_pk: Any,
    shipment_id: Any | None = None,
    movement_id: Any | None = None,
) -> dict[str, Any]:
    """Run all dashboard explain helpers (requires DB connection)."""
    reports = [
        explain_booking_selector_query(driver_pk),
        explain_movement_selector_query(driver_pk),
    ]
    if shipment_id is not None:
        reports.append(
            explain_action_log_scope_query(
                shipment_id=shipment_id,
                driver_id=driver_pk,
            )
        )
    if movement_id is not None:
        reports.append(
            explain_action_log_scope_query(
                movement_id=movement_id,
                driver_id=driver_pk,
            )
        )
    return {'reports': reports, 'driver_pk': str(driver_pk)}
