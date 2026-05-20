"""
mobile_api/services/driver_dashboard_counters.py

Driver-scoped operational counters for the home dashboard.

Uses conditional ``Count`` aggregates (no per-row loops, no action-log scans).
Shipment scope is applied via a subquery so each driver row is counted once.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count, Q

from mobile_api.helpers.dashboard_aggregations import (
    dashboard_counter_dates,
    driver_shipment_counter_scope_q,
    movement_active_filter_q,
    shipment_active_filter_q,
    shipment_cod_pending_filter_q,
    shipment_completed_today_filter_q,
    shipment_completed_week_filter_q,
    shipment_pod_pending_filter_q,
    shipment_pending_action_filter_q,
)
from mobile_api.helpers.operational_status import (
    driver_movement_scope_q,
    shipment_completed_statuses,
)


def _aggregate_shipment_counters(*, driver) -> dict[str, int]:
    from tenant_workspace.models import TenantShipment

    pod_compliant = TenantShipment.PodStatus.COMPLIANT
    collection_pending = TenantShipment.CollectionStatus.PENDING
    completed_statuses = shipment_completed_statuses()
    today, week_start = dashboard_counter_dates()

    shipment_qs = TenantShipment.objects.filter(
        driver_shipment_counter_scope_q(driver),
    )

    agg = shipment_qs.aggregate(
        active_shipments=Count('pk', filter=shipment_active_filter_q()),
        pending_pod=Count(
            'pk',
            filter=shipment_pod_pending_filter_q(pod_compliant=pod_compliant),
        ),
        cod_pending=Count(
            'pk',
            filter=shipment_cod_pending_filter_q(collection_pending=collection_pending),
        ),
        pending_action_shipments=Count(
            'pk',
            filter=shipment_pending_action_filter_q(
                pod_compliant=pod_compliant,
                collection_pending=collection_pending,
            ),
        ),
        completed_today=Count(
            'pk',
            filter=shipment_completed_today_filter_q(
                today=today,
                completed_statuses=completed_statuses,
            ),
        ),
        completed_this_week=Count(
            'pk',
            filter=shipment_completed_week_filter_q(
                week_start=week_start,
                today=today,
                completed_statuses=completed_statuses,
            ),
        ),
    )
    return {key: int(agg.get(key) or 0) for key in agg}


def _aggregate_movement_counters(*, driver) -> dict[str, int]:
    from tenant_workspace.models import TenantTruckMovementLog

    agg = (
        TenantTruckMovementLog.objects.filter(driver_movement_scope_q(driver))
        .aggregate(
            active_movements=Count('pk', filter=movement_active_filter_q()),
        )
    )
    return {'active_movements': int(agg.get('active_movements') or 0)}


def compute_pending_actions(
    *,
    pending_action_shipments: int,
    active_movements: int,
) -> int:
    """
    Actionable workload count: attention-needed shipments plus active movements.

    Avoids inflating with ``active_shipments`` (POD/COD are subsets of active rows).
    """
    return int(pending_action_shipments) + int(active_movements)


def build_dashboard_counters(*, driver) -> dict[str, int]:
    """
    Return all dashboard counter fields for ``data.counters``.

    Query budget: 2 round-trips (one shipment aggregate, one movement aggregate).
    """
    shipment_counts = _aggregate_shipment_counters(driver=driver)
    movement_counts = _aggregate_movement_counters(driver=driver)

    active_movements = movement_counts['active_movements']
    pending_action_shipments = shipment_counts.pop('pending_action_shipments', 0)

    return {
        'active_shipments': shipment_counts['active_shipments'],
        'active_movements': active_movements,
        'pending_pod': shipment_counts['pending_pod'],
        'cod_pending': shipment_counts['cod_pending'],
        'completed_today': shipment_counts['completed_today'],
        'completed_this_week': shipment_counts['completed_this_week'],
        'pending_actions': compute_pending_actions(
            pending_action_shipments=pending_action_shipments,
            active_movements=active_movements,
        ),
    }


def build_dashboard_counters_snapshot(counters: dict[str, Any]) -> dict[str, int]:
    """Subset for welcome ``operational_context.counters_snapshot``."""
    keys = (
        'active_shipments',
        'active_movements',
        'pending_pod',
        'cod_pending',
        'pending_actions',
        'completed_today',
        'completed_this_week',
    )
    return {key: int(counters.get(key) or 0) for key in keys}
