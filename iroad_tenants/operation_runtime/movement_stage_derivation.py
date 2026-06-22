"""
Derive empty / movement-only execution sub-stages from status + action logs.
"""

from __future__ import annotations

from tenant_workspace.models import TenantOperationActionLog, TenantTruckMovementLog
from iroad_tenants.operation_runtime.movement_state_machine import (
    MOVEMENT_COLUMN_SCHEDULED,
    STAGE_ARRIVED,
    STAGE_CANCELLED,
    STAGE_COMPLETED,
    STAGE_CREATED,
    STAGE_IN_TRANSIT,
    STAGE_STARTED,
    execution_stage_label,
    is_movement_arrived_action,
    is_movement_complete_action,
    is_movement_in_transit_action,
    is_movement_start_action,
    is_terminal_movement_status,
)


def _apply_log_to_milestone_flags(flags: dict[str, bool], log) -> None:
    act = getattr(log, 'operation_action', None)
    if is_movement_start_action(act):
        flags['start_done'] = True
    if is_movement_in_transit_action(act):
        flags['in_transit_done'] = True
    if is_movement_arrived_action(act):
        flags['arrived_done'] = True
    if is_movement_complete_action(act):
        flags['complete_done'] = True


def _cascade_milestone_flags(flags: dict[str, bool]) -> dict[str, bool]:
    """Later milestones imply earlier ones (EM4 → delivery → in transit → pickup)."""
    if flags.get('complete_done'):
        flags['arrived_done'] = True
        flags['in_transit_done'] = True
        flags['start_done'] = True
    elif flags.get('arrived_done'):
        flags['in_transit_done'] = True
        flags['start_done'] = True
    elif flags.get('in_transit_done'):
        flags['start_done'] = True
    return flags


def movement_log_milestone_flags_from_logs(
    logs,
    *,
    exclude_log_id=None,
) -> dict[str, bool]:
    flags = {
        'start_done': False,
        'in_transit_done': False,
        'arrived_done': False,
        'complete_done': False,
    }
    for log in logs or []:
        if exclude_log_id and getattr(log, 'log_id', None) == exclude_log_id:
            continue
        _apply_log_to_milestone_flags(flags, log)
    return _cascade_milestone_flags(flags)


def movement_log_milestone_flags(
    movement,
    *,
    exclude_log_id=None,
) -> dict[str, bool]:
    if movement is None:
        return {
            'start_done': False,
            'in_transit_done': False,
            'arrived_done': False,
            'complete_done': False,
        }

    qs = TenantOperationActionLog.objects.filter(
        truck_movement_id=movement.pk,
    ).exclude(operation_action__isnull=True)
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)

    flags = {
        'start_done': False,
        'in_transit_done': False,
        'arrived_done': False,
        'complete_done': False,
    }
    for log in qs.select_related('operation_action').order_by('-log_date', '-created_at')[:200]:
        _apply_log_to_milestone_flags(flags, log)
    return _cascade_milestone_flags(flags)


def movement_has_log_milestones(
    movement,
    *,
    exclude_log_id=None,
) -> bool:
    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)
    return any(flags.values())


def movement_workflow_column_for_policy(
    movement,
    *,
    exclude_log_id=None,
) -> str:
    """
    Column value the movement policy engine should use.

    When the DB column was advanced without action logs, treat as Scheduled so
    EM1 → EM2 → EM3 → EM4 can run from the driver app.
    """
    if movement is None:
        return ''
    current = (movement.status or '').strip()
    if not current:
        return ''
    if movement_has_log_milestones(movement, exclude_log_id=exclude_log_id):
        return current
    if current in (
        TenantTruckMovementLog.Status.IN_PROGRESS,
        TenantTruckMovementLog.Status.COMPLETED,
        TenantTruckMovementLog.Status.CANCELLED,
    ):
        return MOVEMENT_COLUMN_SCHEDULED
    return current


def _stage_from_milestone_flags(flags: dict[str, bool]) -> str:
    """Map EM1–EM4 log milestones to execution sub-stage."""
    if flags.get('complete_done'):
        return STAGE_COMPLETED
    if flags.get('arrived_done'):
        return STAGE_ARRIVED
    if flags.get('in_transit_done'):
        return STAGE_IN_TRANSIT
    if flags.get('start_done'):
        return STAGE_STARTED
    return STAGE_CREATED


def derive_movement_execution_stage(
    movement,
    *,
    exclude_log_id=None,
    status_for_stage: str | None = None,
) -> str:
    """
    Created → Started → In Transit → Arrived → Completed | Cancelled.

    Column ``Scheduled`` / ``In Progress`` pair with log milestones for mid stages.
    Terminal column values (Completed / Cancelled) require matching action-log
    milestones — otherwise the stage falls back to Created so drivers can restart.
    """
    if movement is None:
        return ''

    current = (status_for_stage or movement.status or '').strip()
    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)

    if current == TenantTruckMovementLog.Status.CANCELLED:
        if any(flags.values()):
            return STAGE_CANCELLED
        return STAGE_CREATED
    if current == TenantTruckMovementLog.Status.COMPLETED:
        if flags['complete_done']:
            return STAGE_COMPLETED
        return _stage_from_milestone_flags(flags)

    if current in (
        TenantTruckMovementLog.Status.SCHEDULED,
        TenantTruckMovementLog.Status.IN_PROGRESS,
    ):
        if not any(flags.values()):
            return STAGE_CREATED
        return _stage_from_milestone_flags(flags)

    if is_terminal_movement_status(current):
        if flags['complete_done']:
            return STAGE_COMPLETED
        return _stage_from_milestone_flags(flags)

    if any(flags.values()):
        return _stage_from_milestone_flags(flags)
    return STAGE_CREATED


def derive_movement_operational_stage(
    movement,
    *,
    exclude_log_id=None,
    status_for_stage: str | None = None,
) -> str:
    """Human label for mobile job detail / allowed-actions."""
    stage = derive_movement_execution_stage(
        movement,
        exclude_log_id=exclude_log_id,
        status_for_stage=status_for_stage,
    )
    label = execution_stage_label(stage)
    if label:
        return label
    return (movement.status or '').strip() if movement else ''


def derive_movement_latest_execution_state(
    movement,
    *,
    exclude_log_id=None,
) -> dict:
    """Latest-state block for movement-only job detail."""
    if movement is None:
        return {
            'movement_status': None,
            'derived_status': None,
            'execution_sub_stage': None,
            'operational_stage': None,
            'in_sync': True,
        }

    sub_stage = derive_movement_execution_stage(
        movement,
        exclude_log_id=exclude_log_id,
    )
    current = movement.status
    derived_column = current
    if sub_stage == STAGE_COMPLETED:
        derived_column = TenantTruckMovementLog.Status.COMPLETED
    elif sub_stage == STAGE_CANCELLED:
        derived_column = TenantTruckMovementLog.Status.CANCELLED
    elif sub_stage in (STAGE_STARTED, STAGE_IN_TRANSIT, STAGE_ARRIVED):
        derived_column = TenantTruckMovementLog.Status.IN_PROGRESS

    operational = derive_movement_operational_stage(
        movement,
        exclude_log_id=exclude_log_id,
    )
    return {
        'movement_status': current,
        'derived_status': derived_column,
        'execution_sub_stage': sub_stage,
        'operational_stage': operational,
        'in_sync': derived_column == current or sub_stage in (
            STAGE_IN_TRANSIT,
            STAGE_ARRIVED,
            STAGE_STARTED,
        ),
    }


def sync_movement_timestamps_from_stage(movement, *, stage: str) -> None:
    """Stamp start/end times when movement enters started / completed."""
    from django.utils import timezone

    if movement is None:
        return
    now = timezone.now()
    update_fields = []
    if stage in (STAGE_STARTED, STAGE_IN_TRANSIT) and movement.start_time is None:
        movement.start_time = now
        update_fields.append('start_time')
    if stage == STAGE_COMPLETED and movement.end_time is None:
        movement.end_time = now
        update_fields.append('end_time')
    if update_fields:
        update_fields.append('updated_at')
        movement.save(update_fields=update_fields)
