"""
mobile_api/helpers/job_detail_perf.py

Batched reads for Job Detail — one action-log scan for preview + latest + state.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.services.timeline_service import TimelineService
from mobile_api.helpers.job_detail_guards import job_detail_log_scan_limit
from mobile_api.helpers.job_detail_params import job_detail_timeline_preview_limit
from mobile_api.helpers.timeline_projections import (
    batch_media_previews_by_log,
    project_timeline_item,
)


def resolve_log_fetch_limit(
    *,
    include_timeline_preview: bool,
    include_execution_state: bool,
    preview_limit: int | None = None,
    scan_limit: int | None = None,
) -> int:
    """Single cap for how many log rows to load from the database."""
    preview = preview_limit if preview_limit is not None else job_detail_timeline_preview_limit()
    scan = scan_limit if scan_limit is not None else job_detail_log_scan_limit()
    need = 0
    if include_timeline_preview:
        need = max(need, preview)
    if include_execution_state:
        need = max(need, scan)
    return need


def load_scoped_action_logs(
    *,
    shipment=None,
    movement=None,
    driver_id=None,
    limit: int,
) -> list:
    """
    Driver-scoped action logs (newest first), bounded, with ``select_related``.
    """
    if limit <= 0:
        return []
    return TimelineService.fetch_scoped_timeline_page(
        shipment=shipment,
        movement=movement,
        driver_id=driver_id,
        limit=limit,
    )


def latest_log_from_rows(log_rows: list) -> Any:
    return log_rows[0] if log_rows else None


def build_timeline_preview_items(
    log_rows: list,
    *,
    request=None,
    preview_limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Project timeline preview rows with batched media (no per-log media queries).
    """
    cap = preview_limit if preview_limit is not None else job_detail_timeline_preview_limit()
    page_rows = log_rows[:cap]
    if not page_rows:
        return []
    log_ids = [row.log_id for row in page_rows]
    media_map = batch_media_previews_by_log(log_ids, request=request)
    return [
        project_timeline_item(
            row,
            request=request,
            media_previews=media_map.get(str(row.log_id), []),
        )
        for row in page_rows
    ]


def reconcile_shipment_state_from_logs(
    shipment,
    *,
    movement=None,
    driver_id=None,
    log_rows: list,
    request=None,
) -> dict[str, Any]:
    from iroad_tenants.operation_runtime.workflow_state_reconciler import (
        reconcile_shipment_execution_state,
    )

    state = reconcile_shipment_execution_state(
        shipment,
        movement=movement,
        driver_id=driver_id,
        request=request,
        prefetched_logs=log_rows,
    )
    from iroad_tenants.services.latest_state_service import _public_execution_state

    return _public_execution_state(state)


def lock_entities_for_execution(*, shipment=None, movement=None):
    """
    Row-level locks to reduce concurrent execute races on the same job.

    Returns refreshed shipment/movement instances (or originals when lock skipped).
    """
    locked_shipment = shipment
    locked_movement = movement
    if shipment is not None:
        from tenant_workspace.models import TenantShipment

        row = (
            TenantShipment.objects.select_for_update()
            .filter(pk=shipment.pk)
            .first()
        )
        if row is not None:
            locked_shipment = row
    if movement is not None:
        from tenant_workspace.models import TenantTruckMovementLog

        row = (
            TenantTruckMovementLog.objects.select_for_update()
            .filter(pk=movement.pk)
            .first()
        )
        if row is not None:
            locked_movement = row
    return locked_shipment, locked_movement


def reconcile_movement_state_from_logs(
    movement,
    *,
    driver_id=None,
    log_rows: list,
    request=None,
) -> dict[str, Any]:
    from iroad_tenants.operation_runtime.workflow_state_reconciler import (
        reconcile_movement_execution_state,
    )

    state = reconcile_movement_execution_state(
        movement,
        driver_id=driver_id,
        request=request,
        prefetched_logs=log_rows,
    )
    from iroad_tenants.services.latest_state_service import _public_execution_state

    return _public_execution_state(state)
