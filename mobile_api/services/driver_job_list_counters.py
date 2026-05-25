"""
mobile_api/services/driver_job_list_counters.py

Driver-scoped operational counters for ``GET /driver/jobs/summary/``.

Independent mobile payload from the home dashboard (tab-aligned counts only).
Reuses dashboard aggregation Q objects — two DB round-trips, no row loops.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Count

from mobile_api.helpers.dashboard_aggregations import driver_shipment_counter_scope_q
from mobile_api.helpers.job_list_aggregations import (
    job_list_movement_counter_filters,
    job_list_shipment_counter_filters,
)
from mobile_api.helpers.operational_status import driver_movement_scope_q


def _int_agg(agg: dict[str, Any]) -> dict[str, int]:
    return {key: int(agg.get(key) or 0) for key in agg}


def aggregate_job_list_shipment_counters(*, driver) -> dict[str, int]:
    """
    One conditional aggregate query over driver-scoped shipments.

    Uses ``driver_shipment_counter_scope_q`` (same scope as list feeds).
    """
    from tenant_workspace.models import TenantShipment

    pod_compliant = TenantShipment.PodStatus.COMPLIANT
    collection_pending = TenantShipment.CollectionStatus.PENDING
    filters = job_list_shipment_counter_filters(
        pod_compliant=pod_compliant,
        collection_pending=collection_pending,
    )

    shipment_qs = TenantShipment.objects.filter(
        driver_shipment_counter_scope_q(driver),
    )
    agg_kwargs = {
        key: Count('pk', filter=q_filter)
        for key, q_filter in filters.items()
    }
    return _int_agg(shipment_qs.aggregate(**agg_kwargs))


def aggregate_job_list_movement_counters(*, driver) -> dict[str, int]:
    """One conditional aggregate query over driver-scoped movements."""
    from tenant_workspace.models import TenantTruckMovementLog

    filters = job_list_movement_counter_filters()
    movement_qs = TenantTruckMovementLog.objects.filter(
        driver_movement_scope_q(driver),
    )
    agg_kwargs = {
        key: Count('pk', filter=q_filter)
        for key, q_filter in filters.items()
    }
    return _int_agg(movement_qs.aggregate(**agg_kwargs))


def project_job_list_summary_counters(
    shipment_counts: dict[str, int],
    movement_counts: dict[str, int],
) -> dict[str, int]:
    """
    Flat mobile summary contract for My Jobs landing badges.

    Field names match list tab routes (``/shipments/active/``, etc.).
    """
    return {
        'active_shipments': shipment_counts.get('active_shipments', 0),
        'completed_shipments': shipment_counts.get('completed_shipments', 0),
        'cancelled_shipments': shipment_counts.get('cancelled_shipments', 0),
        'active_movements': movement_counts.get('active_movements', 0),
        'completed_movements': movement_counts.get('completed_movements', 0),
        'cancelled_movements': movement_counts.get('cancelled_movements', 0),
        'pod_pending': shipment_counts.get('pod_pending', 0),
        'cod_pending': shipment_counts.get('cod_pending', 0),
    }


def build_job_list_counters(*, driver) -> dict[str, int]:
    """
    Full job list summary counters (2 aggregate queries).

    Not interchangeable with ``build_dashboard_counters`` — no
    ``completed_today``, ``pending_actions``, or dashboard-only fields.
    """
    shipment_counts = aggregate_job_list_shipment_counters(driver=driver)
    movement_counts = aggregate_job_list_movement_counters(driver=driver)
    return project_job_list_summary_counters(shipment_counts, movement_counts)
