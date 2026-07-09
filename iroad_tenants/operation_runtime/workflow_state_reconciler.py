"""
Reconcile column caches with action-log authoritative state (drift detection).
"""

from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantTruckMovementLog

from iroad_tenants.operation_runtime.execution_stage_deriver import (
    derive_job_execution_stage,
)
from iroad_tenants.operation_runtime.latest_action_aggregator import (
    aggregate_latest_action_log,
    derive_movement_status_from_logs,
    derive_shipment_status_from_logs,
    movement_status_rank,
    scoped_movement_action_logs,
    scoped_shipment_action_logs,
    shipment_status_rank,
)
from iroad_tenants.operation_runtime.latest_state import (
    derive_latest_action_status,
    sync_shipment_status_from_action_log,
)
from iroad_tenants.operation_runtime.movement_stage_derivation import (
    movement_log_milestone_flags,
    movement_log_milestone_flags_from_logs,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    MOVEMENT_COLUMN_SCHEDULED,
    is_terminal_movement_status,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    STAGE_PICKUP,
    STAGE_LOADING,
    STAGE_PRE_TRANSIT,
)


def _column_behind_authoritative(column: str | None, authoritative: str | None) -> bool:
    """True when the DB column lags workflow milestone / impact evidence."""
    auth = (authoritative or '').strip()
    if not auth:
        return False
    col = (column or '').strip()
    if not col:
        return True
    return shipment_status_rank(auth) > shipment_status_rank(col)


def _auto_repair_status_drift_enabled() -> bool:
    try:
        from django.conf import settings

        return bool(getattr(settings, 'MOBILE_API_JOBS_AUTO_REPAIR_STATUS_DRIFT', False))
    except Exception:
        return False


def _build_drift(
    *,
    column_status: str | None,
    authoritative_status: str | None,
    latest_impact_status: str | None,
    peak_impact_status: str | None,
    execution_sub_stage: str,
) -> dict[str, Any]:
    column = (column_status or '').strip()
    authoritative = (authoritative_status or '').strip()
    latest = (latest_impact_status or '').strip()
    peak = (peak_impact_status or '').strip()

    has_status_drift = False
    reason = ''

    if authoritative and column and authoritative != column:
        col_rank = shipment_status_rank(column)
        auth_rank = shipment_status_rank(authoritative)
        if auth_rank != col_rank:
            has_status_drift = True
            if auth_rank > col_rank:
                reason = 'column_behind_action_logs'
            else:
                reason = 'column_ahead_of_action_logs'

    stage_drift = False
    if execution_sub_stage in (STAGE_PICKUP, STAGE_LOADING, STAGE_PRE_TRANSIT):
        if column and shipment_status_rank(column) > shipment_status_rank('Loaded'):
            stage_drift = True
            if not reason:
                reason = 'early_stage_logs_column_advanced'

    has_drift = has_status_drift or stage_drift

    return {
        'has_drift': has_drift,
        'has_status_drift': has_status_drift,
        'has_stage_drift': stage_drift,
        'column_status': column or None,
        'authoritative_status': authoritative or None,
        'latest_log_impact_status': latest or None,
        'peak_log_impact_status': peak or None,
        'reason': reason or None,
        'recommended_column_status': authoritative if has_status_drift and authoritative else None,
    }


def reconcile_shipment_execution_state(
    shipment,
    *,
    movement=None,
    driver_id=None,
    exclude_log_id=None,
    request=None,
    prefetched_logs: list | None = None,
) -> dict[str, Any]:
    """
    Authoritative job-detail execution state for a shipment (optional linked movement).

    When ``prefetched_logs`` is supplied (e.g. mobile job detail batch read), skip
    a second ORM scan of action logs.
    """
    if prefetched_logs is not None:
        logs = prefetched_logs
    else:
        logs = list(
            scoped_shipment_action_logs(
                shipment,
                movement=movement,
                driver_id=driver_id,
                exclude_log_id=exclude_log_id,
            )
        )
    log_evidence = derive_shipment_status_from_logs(logs)
    authoritative = log_evidence.get('authoritative_status')
    column = (shipment.shipment_status or '').strip() if shipment else ''

    stage_block = derive_job_execution_stage(
        shipment=shipment,
        movement=movement,
        authoritative_shipment_status=authoritative,
        exclude_log_id=exclude_log_id,
        prefetched_logs=logs,
    )
    sub_stage = stage_block.get('execution_sub_stage') or ''
    operational = stage_block.get('operational_stage') or ''

    drift = _build_drift(
        column_status=column,
        authoritative_status=authoritative,
        latest_impact_status=log_evidence.get('latest_impact_status'),
        peak_impact_status=log_evidence.get('peak_impact_status'),
        execution_sub_stage=sub_stage,
    )

    hybrid_derived = derive_latest_action_status(shipment) if shipment else None
    repair_target = authoritative or hybrid_derived
    if shipment is not None and (
        _column_behind_authoritative(column, repair_target)
        or (
            _auto_repair_status_drift_enabled()
            and drift.get('has_status_drift')
        )
    ):
        from iroad_tenants.operation_runtime.latest_state import (
            sync_shipment_status_from_action_log,
        )

        sync_shipment_status_from_action_log(shipment)
        shipment.refresh_from_db()
        column = (shipment.shipment_status or '').strip()
        drift = _build_drift(
            column_status=column,
            authoritative_status=authoritative,
            latest_impact_status=log_evidence.get('latest_impact_status'),
            peak_impact_status=log_evidence.get('peak_impact_status'),
            execution_sub_stage=sub_stage,
        )
        hybrid_derived = derive_latest_action_status(shipment)

    in_sync = not drift.get('has_drift') and (
        (authoritative is None)
        or (column == authoritative)
        or (hybrid_derived == column if hybrid_derived else True)
    )

    return {
        'entity_type': 'shipment',
        'shipment_status': column or None,
        'column_status': column or None,
        'movement_status': movement.status if movement else None,
        'derived_status': authoritative,
        'authoritative_status': authoritative,
        'hybrid_latest_log_status': hybrid_derived,
        'execution_sub_stage': sub_stage,
        'operational_stage': operational,
        'in_sync': in_sync,
        'state_source': 'action_logs',
        'drift': drift,
        'timeline': {
            'log_count': log_evidence.get('log_count', 0),
            'reversal_log_count': log_evidence.get('reversal_log_count', 0),
        },
        'latest_action': aggregate_latest_action_log(logs, request=request),
    }


def reconcile_movement_execution_state(
    movement,
    *,
    driver_id=None,
    exclude_log_id=None,
    request=None,
    prefetched_logs: list | None = None,
) -> dict[str, Any]:
    if prefetched_logs is not None:
        logs = prefetched_logs
    else:
        logs = list(
            scoped_movement_action_logs(
                movement,
                driver_id=driver_id,
                exclude_log_id=exclude_log_id,
            )
        )
    log_evidence = derive_movement_status_from_logs(logs)
    authoritative = log_evidence.get('authoritative_status')
    column = (movement.status or '').strip() if movement else ''
    log_count = int(log_evidence.get('log_count') or 0)
    if prefetched_logs is not None:
        flags = movement_log_milestone_flags_from_logs(
            logs,
            exclude_log_id=exclude_log_id,
        )
    else:
        flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)

    workflow_authoritative = authoritative
    has_drift = False
    drift_reason = None
    if flags.get('complete_done'):
        workflow_authoritative = TenantTruckMovementLog.Status.COMPLETED
        if column != TenantTruckMovementLog.Status.COMPLETED:
            has_drift = True
            drift_reason = 'complete_log_without_completed_column'
    elif (
        workflow_authoritative == TenantTruckMovementLog.Status.COMPLETED
        and not flags.get('complete_done')
    ):
        workflow_authoritative = TenantTruckMovementLog.Status.IN_PROGRESS
        has_drift = True
        drift_reason = 'completed_column_without_em4_log'
    elif column == TenantTruckMovementLog.Status.COMPLETED and not flags.get('complete_done'):
        workflow_authoritative = TenantTruckMovementLog.Status.IN_PROGRESS
        has_drift = True
        drift_reason = drift_reason or 'completed_column_without_em4_log'
    if log_count <= 0 and column:
        workflow_authoritative = MOVEMENT_COLUMN_SCHEDULED
        if column != MOVEMENT_COLUMN_SCHEDULED:
            has_drift = True
            if is_terminal_movement_status(column):
                drift_reason = 'terminal_column_without_action_logs'
            else:
                drift_reason = 'column_without_action_logs'
    elif authoritative and column and authoritative != column:
        has_drift = True
        drift_reason = 'movement_column_behind_logs'

    stage_block = derive_job_execution_stage(
        movement=movement,
        authoritative_movement_status=workflow_authoritative,
        exclude_log_id=exclude_log_id,
        prefetched_logs=logs,
    )
    sub_stage = stage_block.get('execution_sub_stage') or ''
    operational = stage_block.get('operational_stage') or ''

    drift = {
        'has_drift': has_drift,
        'has_status_drift': has_drift,
        'has_stage_drift': False,
        'column_status': column or None,
        'authoritative_status': workflow_authoritative or None,
        'latest_log_impact_status': log_evidence.get('latest_impact_status'),
        'peak_log_impact_status': log_evidence.get('peak_impact_status'),
        'reason': drift_reason,
        'recommended_column_status': workflow_authoritative if has_drift else None,
    }

    return {
        'entity_type': 'movement',
        'shipment_status': None,
        'column_status': None,
        'movement_status': column or None,
        'derived_status': workflow_authoritative,
        'authoritative_status': workflow_authoritative,
        'execution_sub_stage': sub_stage,
        'operational_stage': operational,
        'in_sync': not has_drift,
        'state_source': 'action_logs',
        'drift': drift,
        'timeline': {'log_count': log_count},
        'latest_action': aggregate_latest_action_log(logs, request=request),
    }


def reconcile_job_execution_state(
    *,
    shipment=None,
    movement=None,
    driver_id=None,
    exclude_log_id=None,
    request=None,
) -> dict[str, Any]:
    if shipment is not None:
        return reconcile_shipment_execution_state(
            shipment,
            movement=movement,
            driver_id=driver_id,
            exclude_log_id=exclude_log_id,
            request=request,
        )
    if movement is not None:
        return reconcile_movement_execution_state(
            movement,
            driver_id=driver_id,
            exclude_log_id=exclude_log_id,
            request=request,
        )
    return {
        'entity_type': '',
        'in_sync': True,
        'state_source': 'action_logs',
        'drift': {'has_drift': False},
    }


def validate_shipment_state_consistency(shipment, *, movement=None) -> list[str]:
    """Human-readable consistency warnings (non-blocking)."""
    state = reconcile_shipment_execution_state(shipment, movement=movement)
    warnings: list[str] = []
    drift = state.get('drift') or {}
    if drift.get('has_drift'):
        warnings.append(
            f"Shipment status drift: column={drift.get('column_status')} "
            f"logs={drift.get('authoritative_status')} ({drift.get('reason')})"
        )
    if not state.get('latest_action') and (state.get('timeline') or {}).get('log_count', 0) == 0:
        warnings.append('No operation action logs found for shipment scope.')
    return warnings
