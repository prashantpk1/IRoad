"""
mobile_api/helpers/dashboard_aggregations.py

Reusable Q objects and status sets for driver dashboard conditional aggregates.

Keeps counter semantics aligned with the tenant portal without importing portal views.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from mobile_api.helpers.operational_status import (
    MOVEMENT_ACTIVE_STATUSES,
    driver_shipment_scope_q,
    shipment_active_statuses,
    shipment_completed_statuses,
)


def driver_shipment_counter_scope_q(driver) -> Q:
    """
    Driver shipment scope for counter aggregates.

    Uses the same OR filter as list views; each shipment row is counted once (no
    ``pk__in`` subquery materialization).
    """
    return driver_shipment_scope_q(driver)


def driver_shipment_counter_subquery_q(driver) -> Q:
    """Backward-compatible alias — prefer ``driver_shipment_counter_scope_q``."""
    return driver_shipment_counter_scope_q(driver)


def driver_shipment_scope_pk_list(driver, *, max_rows: int | None = None) -> list:
    """
    Materialized shipment PK list for ``__in`` filters (POD activity, etc.).

    Capped to avoid huge ``IN`` clauses on drivers with very large histories.
    """
    from django.conf import settings

    if max_rows is None:
        max_rows = int(
            getattr(settings, 'MOBILE_API_DASHBOARD_SHIPMENT_SCOPE_PK_CAP', 500) or 500
        )
    cap = max(1, int(max_rows))
    return list(
        driver_shipment_scope_qs(driver)
        .order_by('-updated_at')
        .values_list('pk', flat=True)[:cap]
    )


def driver_shipment_scope_qs(driver):
    """Base queryset for driver-scoped shipment counters (no select_related)."""
    from tenant_workspace.models import TenantShipment

    return TenantShipment.objects.filter(driver_shipment_scope_q(driver))


def shipment_active_filter_q() -> Q:
    return Q(shipment_status__in=shipment_active_statuses())


def shipment_pod_pending_filter_q(*, pod_compliant: str) -> Q:
    """In-flight shipments that still need POD compliance."""
    return shipment_active_filter_q() & ~Q(pod_status=pod_compliant)


def shipment_cod_pending_filter_q(*, collection_pending: str) -> Q:
    """In-flight COD shipments awaiting collection."""
    return (
        shipment_active_filter_q()
        & Q(collection_status=collection_pending)
        & (Q(order_type__iexact='COD') | Q(cod_amount__gt=0))
    )


def shipment_completed_today_filter_q(*, today: date, completed_statuses: tuple[str, ...]) -> Q:
    return Q(
        shipment_status__in=completed_statuses,
        updated_at__date=today,
    )


def shipment_completed_week_filter_q(
    *,
    week_start: date,
    today: date,
    completed_statuses: tuple[str, ...],
) -> Q:
    return Q(
        shipment_status__in=completed_statuses,
        updated_at__date__gte=week_start,
        updated_at__date__lte=today,
    )


def shipment_pending_action_filter_q(*, pod_compliant: str, collection_pending: str) -> Q:
    """Shipments needing driver attention (POD or COD), excluding double-count in movements."""
    return shipment_pod_pending_filter_q(pod_compliant=pod_compliant) | shipment_cod_pending_filter_q(
        collection_pending=collection_pending
    )


def movement_active_filter_q() -> Q:
    return Q(status__in=MOVEMENT_ACTIVE_STATUSES)


def dashboard_counter_dates(*, tz=None) -> tuple[date, date]:
    """Return ``(today, week_start_monday)`` in the active timezone."""
    now = timezone.now()
    if tz is not None:
        now = timezone.localtime(now, tz)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    return today, week_start


def merge_counter_aggregates(*parts: dict[str, int]) -> dict[str, int]:
    """Sum numeric counter keys across partial aggregate dicts."""
    merged: dict[str, int] = {}
    for part in parts:
        for key, value in part.items():
            merged[key] = int(merged.get(key, 0)) + int(value or 0)
    return merged
