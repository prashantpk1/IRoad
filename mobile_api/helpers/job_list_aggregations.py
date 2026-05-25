"""
mobile_api/helpers/job_list_aggregations.py

Conditional aggregate Q objects for the driver job list summary API.

Reuses dashboard counter semantics (``dashboard_aggregations``) and aligns
completed/cancelled counts with job list tab filters (``job_list_filters``).
"""
from __future__ import annotations

from django.db.models import Q

from mobile_api.helpers.dashboard_aggregations import (
    driver_shipment_counter_scope_q,
    movement_active_filter_q,
    shipment_active_filter_q,
    shipment_cod_pending_filter_q,
    shipment_pod_pending_filter_q,
)
from mobile_api.helpers.operational_status import (
    SHIPMENT_CANCELLED_STATUSES,
    movement_cancelled_filter_q,
    movement_completed_filter_q,
    shipment_completed_statuses,
)


def shipment_completed_tab_filter_q() -> Q:
    """Completed tab — Delivered / Closed (same as list ``tab=completed``)."""
    return Q(shipment_status__in=shipment_completed_statuses())


def shipment_cancelled_tab_filter_q() -> Q:
    """Cancelled tab — matches list ``tab=cancelled``."""
    return Q(shipment_status__in=SHIPMENT_CANCELLED_STATUSES)


def job_list_shipment_counter_filters(*, pod_compliant: str, collection_pending: str) -> dict[str, Q]:
    """Named filters for a single shipment ``aggregate(Count(..., filter=...))`` call."""
    return {
        'active_shipments': shipment_active_filter_q(),
        'completed_shipments': shipment_completed_tab_filter_q(),
        'cancelled_shipments': shipment_cancelled_tab_filter_q(),
        'pod_pending': shipment_pod_pending_filter_q(pod_compliant=pod_compliant),
        'cod_pending': shipment_cod_pending_filter_q(collection_pending=collection_pending),
    }


def job_list_movement_counter_filters() -> dict[str, Q]:
    """Named filters for a single movement aggregate call."""
    return {
        'active_movements': movement_active_filter_q(),
        'completed_movements': movement_completed_filter_q(),
        'cancelled_movements': movement_cancelled_filter_q(),
    }
