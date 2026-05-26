"""
Planner-friendly timeline query shapes for job detail action logs.

Shipment scope uses UNION ALL of two index-backed projections (direct shipment FK
and movement FK via subquery) instead of ``shipment_id OR truck_movement__shipment_id``,
which forces a join and weakens composite index use.

Movement scope uses a single ``truck_movement_id`` filter (``tenant_oal_move_drv_dt_id_idx``).
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery

from iroad_tenants.operation_runtime.timeline_cursor import (
    TimelineCursor,
    apply_timeline_cursor_filter,
)
from tenant_workspace.models import TenantOperationActionLog, TenantTruckMovementLog

# Stable ordering for cursor keyset pagination (matches timeline_cursor filter).
TIMELINE_ORDER = ('-log_date', '-created_at', '-log_id')


def movement_ids_subquery_for_shipment(shipment_pk) -> Subquery:
    """Movement PKs for a shipment — indexed lookup on ``tenant_tml_shipment_idx``."""
    return TenantTruckMovementLog.objects.filter(
        shipment_id=shipment_pk,
    ).values('pk')


def shipment_action_log_scope_q(shipment_pk) -> Q:
    """
    Shipment scope without joining ``truck_movement`` on the action log table.

    Prefer :func:`union_shipment_timeline_querysets` for paginated reads; this Q
    object is used for bounded single-query scans (detail preview / execution timeline).
    """
    movement_ids = movement_ids_subquery_for_shipment(shipment_pk)
    return Q(shipment_id=shipment_pk) | Q(truck_movement_id__in=movement_ids)


def shipment_movement_exists_q(shipment_pk) -> Q:
    """EXISTS-based shipment scope (semantically equivalent to :func:`shipment_action_log_scope_q`)."""
    movement_match = TenantTruckMovementLog.objects.filter(
        pk=OuterRef('truck_movement_id'),
        shipment_id=shipment_pk,
    )
    return Q(shipment_id=shipment_pk) | Q(Exists(movement_match))


def base_action_log_queryset(*, driver_id=None, require_action: bool = True) -> QuerySet:
    qs = TenantOperationActionLog.objects.all()
    if require_action:
        qs = qs.exclude(operation_action__isnull=True)
    if driver_id:
        qs = qs.filter(driver_id=driver_id)
    return qs


def shipment_direct_projection(
    qs: QuerySet,
    shipment_pk,
    *,
    cursor: TimelineCursor | None = None,
) -> QuerySet:
    """Logs with ``shipment_id`` set — uses ``tenant_oal_ship_drv_dt_id_idx``."""
    branch = qs.filter(shipment_id=shipment_pk)
    if cursor is not None:
        branch = apply_timeline_cursor_filter(branch, cursor)
    return branch


def shipment_via_movement_projection(
    qs: QuerySet,
    shipment_pk,
    *,
    cursor: TimelineCursor | None = None,
) -> QuerySet:
    """
    Logs tied to movements on this shipment but not already in the direct branch.

    Uses ``tenant_oal_move_drv_dt_id_idx`` (``truck_movement_id`` IN subquery).
    """
    movement_ids = movement_ids_subquery_for_shipment(shipment_pk)
    branch = qs.filter(truck_movement_id__in=movement_ids).exclude(
        shipment_id=shipment_pk,
    )
    if cursor is not None:
        branch = apply_timeline_cursor_filter(branch, cursor)
    return branch


def union_shipment_timeline_querysets(
    direct: QuerySet,
    via_movement: QuerySet,
) -> QuerySet:
    """UNION ALL merge of shipment direct + movement projections."""
    return direct.union(via_movement, all=True).order_by(*TIMELINE_ORDER)


def scoped_shipment_action_log_queryset(
    *,
    shipment,
    driver_id=None,
    cursor: TimelineCursor | None = None,
    select_related: bool = True,
) -> QuerySet:
    base = base_action_log_queryset(driver_id=driver_id, require_action=True)
    if select_related:
        base = base.select_related(
            'operation_action',
            'driver',
            'shipment',
            'truck_movement',
        )
    direct = shipment_direct_projection(base, shipment.pk, cursor=cursor)
    via_movement = shipment_via_movement_projection(base, shipment.pk, cursor=cursor)
    return union_shipment_timeline_querysets(direct, via_movement)


def scoped_movement_action_log_queryset(
    *,
    movement,
    driver_id=None,
    cursor: TimelineCursor | None = None,
    select_related: bool = True,
) -> QuerySet:
    qs = base_action_log_queryset(driver_id=driver_id, require_action=True)
    if select_related:
        qs = qs.select_related(
            'operation_action',
            'driver',
            'shipment',
            'truck_movement',
        )
    qs = qs.filter(truck_movement_id=movement.pk)
    if cursor is not None:
        qs = apply_timeline_cursor_filter(qs, cursor)
    return qs.order_by(*TIMELINE_ORDER)


def hydrate_action_log_rows(rows: list) -> list:
    """
    Re-fetch union page rows with ``select_related`` (UNION cannot preserve joins).

    Preserves the order of ``rows`` from the union slice.
    """
    if not rows:
        return []
    log_ids = [row.log_id for row in rows]
    enriched = (
        TenantOperationActionLog.objects.filter(log_id__in=log_ids)
        .exclude(operation_action__isnull=True)
        .select_related(
            'operation_action',
            'driver',
            'shipment',
            'truck_movement',
        )
    )
    by_id = {row.log_id: row for row in enriched}
    return [by_id[log_id] for log_id in log_ids if log_id in by_id]


def fetch_timeline_page(
    queryset: QuerySet,
    *,
    limit: int,
    hydrate_union: bool = False,
) -> list:
    """Slice a timeline queryset and optionally hydrate after UNION."""
    rows = list(queryset[:limit])
    if hydrate_union and rows:
        return hydrate_action_log_rows(rows)
    return rows
