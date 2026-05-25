"""
Derive empty / movement-only execution sub-stages from status + action logs.
"""

from __future__ import annotations

from tenant_workspace.models import TenantOperationActionLog, TenantTruckMovementLog
from iroad_tenants.operation_runtime.movement_state_machine import (
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
        act = log.operation_action
        if is_movement_start_action(act):
            flags['start_done'] = True
        if is_movement_in_transit_action(act):
            flags['in_transit_done'] = True
        if is_movement_arrived_action(act):
            flags['arrived_done'] = True
        if is_movement_complete_action(act):
            flags['complete_done'] = True
    return flags


def derive_movement_execution_stage(
    movement,
    *,
    exclude_log_id=None,
) -> str:
    """
    Created → Started → In Transit → Arrived → Completed | Cancelled.

    Column ``Scheduled`` / ``In Progress`` pair with log milestones for mid stages.
    """
    if movement is None:
        return ''

    current = (movement.status or '').strip()
    if current == TenantTruckMovementLog.Status.CANCELLED:
        return STAGE_CANCELLED
    if current == TenantTruckMovementLog.Status.COMPLETED:
        return STAGE_COMPLETED

    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)

    if current == TenantTruckMovementLog.Status.SCHEDULED:
        if flags['start_done']:
            return STAGE_STARTED
        return STAGE_CREATED

    if current == TenantTruckMovementLog.Status.IN_PROGRESS:
        if flags['arrived_done']:
            return STAGE_ARRIVED
        if flags['in_transit_done']:
            return STAGE_IN_TRANSIT
        if flags['start_done']:
            return STAGE_STARTED
        return STAGE_STARTED

    if is_terminal_movement_status(current):
        return STAGE_COMPLETED

    return STAGE_CREATED


def derive_movement_operational_stage(
    movement,
    *,
    exclude_log_id=None,
) -> str:
    """Human label for mobile job detail / allowed-actions."""
    stage = derive_movement_execution_stage(
        movement,
        exclude_log_id=exclude_log_id,
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
