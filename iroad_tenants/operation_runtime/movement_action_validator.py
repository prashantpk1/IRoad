"""
Movement-only action classification and allow/deny rules.
"""

from __future__ import annotations

from iroad_tenants.operation_execution import action_matches
from iroad_tenants.operation_runtime.movement_state_machine import (
    STAGE_ARRIVED,
    STAGE_CANCELLED,
    STAGE_COMPLETED,
    STAGE_CREATED,
    STAGE_IN_TRANSIT,
    STAGE_STARTED,
    is_movement_arrived_action,
    is_movement_cancel_action,
    is_movement_complete_action,
    is_movement_in_transit_action,
    is_movement_lifecycle_action,
    is_movement_start_action,
    is_terminal_movement_status,
    movement_impact_allowed_from_current,
    resolve_action_movement_impact,
)
from iroad_tenants.operation_runtime.movement_stage_derivation import (
    derive_movement_execution_stage,
    movement_log_milestone_flags,
    movement_workflow_column_for_policy,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_pickup_or_loading_action,
)
from tenant_workspace.models import TenantOperationAction, TenantOperationActionLog, TenantTruckMovementLog


def is_empty_movement(movement) -> bool:
    if movement is None:
        return False
    source = str(getattr(movement, 'movement_source', '') or '').strip().lower()
    reason = str(getattr(movement, 'empty_move_reason', '') or '').strip()
    return source == 'empty' or bool(reason)


def is_movement_only_context(*, shipment=None, movement=None) -> bool:
    """Policy uses movement engine when no shipment is on the action context."""
    return movement is not None and shipment is None


def action_applies_to_movement_context(action, *, empty_move: bool) -> bool:
    """Filter Action Master rows for movement-only execution."""
    if action is None:
        return False
    if action.auto_shipment_post and not (action.movement_status_impact or '').strip():
        return False
    if is_pickup_or_loading_action(action):
        return False
    if (action.shipment_status_impact or '').strip():
        return False

    cat = (getattr(action, 'sequence_category', None) or '').strip().lower()
    code = (getattr(action, 'action_code', None) or '').strip().upper()
    if empty_move:
        if cat == 'job' or code.startswith('A'):
            return False
    if (action.movement_status_impact or '').strip():
        return True
    if cat in ('empty_move', 'empty move'):
        return True
    if is_movement_lifecycle_action(action):
        return True
    return bool(action.auto_movement_post)


def validate_movement_completion_stage(movement, *, exclude_log_id=None) -> str | None:
    stage = derive_movement_execution_stage(movement, exclude_log_id=exclude_log_id)
    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)
    if stage not in (STAGE_ARRIVED,) and not flags['arrived_done']:
        return (
            'Movement must reach Arrived before Completed. '
            'Execute In Transit and Arrived actions first.'
        )
    return None


def _movement_executed_action_codes(
    movement,
    *,
    exclude_log_id=None,
) -> set[str]:
    if movement is None:
        return set()
    qs = TenantOperationActionLog.objects.exclude(operation_action__isnull=True)
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    qs = qs.filter(truck_movement_id=movement.pk).select_related('operation_action')
    return {
        (getattr(log.operation_action, 'action_code', '') or '').strip().upper()
        for log in qs
        if getattr(log, 'operation_action', None) is not None
        and (getattr(log.operation_action, 'action_code', '') or '').strip()
    }


def movement_prerequisites_met(
    action,
    movement,
    *,
    exclude_log_id=None,
) -> bool:
    raw = (getattr(action, 'prerequisite_action_codes', None) or '').strip()
    if not raw:
        return True
    required = {
        token.strip().upper()
        for token in raw.split(',')
        if token.strip()
    }
    if not required:
        return True
    executed = _movement_executed_action_codes(
        movement,
        exclude_log_id=exclude_log_id,
    )
    return required.issubset(executed)


def movement_lifecycle_action_allowed(
    action,
    movement,
    *,
    exclude_log_id=None,
) -> bool:
    """Log-sequenced allow rules for non-impact lifecycle actions."""
    stage = derive_movement_execution_stage(movement, exclude_log_id=exclude_log_id)
    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)

    if is_movement_start_action(action):
        return stage == STAGE_CREATED and not flags['start_done']

    if is_movement_in_transit_action(action):
        return stage in (STAGE_STARTED, STAGE_CREATED) and flags['start_done'] and not flags[
            'in_transit_done'
        ]

    if is_movement_arrived_action(action):
        return flags['in_transit_done'] and not flags['arrived_done']

    if is_movement_complete_action(action):
        if validate_movement_completion_stage(movement, exclude_log_id=exclude_log_id):
            return False
        return not flags['complete_done']

    if is_movement_cancel_action(action):
        return not is_terminal_movement_status(movement.status or '')

    return False


def movement_action_is_allowed(
    action,
    movement,
    *,
    exclude_log_id=None,
    executed_action_ids=None,
) -> bool:
    """
    Movement-only policy (empty move and movement-without-shipment job detail).
    """
    if action is None or movement is None:
        return False
    if action.status != TenantOperationAction.Status.ACTIVE:
        return False

    workflow_current = movement_workflow_column_for_policy(
        movement,
        exclude_log_id=exclude_log_id,
    )
    if is_terminal_movement_status(workflow_current) and not is_movement_cancel_action(action):
        if action_matches(action, 'reversal', 'undo', 'r1', 'r2'):
            return True
        return False

    if executed_action_ids and action.action_id in executed_action_ids:
        return False

    empty_move = is_empty_movement(movement)
    if not action_applies_to_movement_context(action, empty_move=empty_move):
        return False

    if not movement_prerequisites_met(
        action,
        movement,
        exclude_log_id=exclude_log_id,
    ):
        return False

    impact = resolve_action_movement_impact(action)
    if impact:
        if is_movement_complete_action(action):
            if validate_movement_completion_stage(movement, exclude_log_id=exclude_log_id):
                return False
        if movement_impact_allowed_from_current(
            current=workflow_current,
            impact_status=impact,
        ):
            return True
        if is_movement_start_action(action):
            return movement_lifecycle_action_allowed(
                action,
                movement,
                exclude_log_id=exclude_log_id,
            )
        return False

    if action.auto_movement_post:
        return False

    if is_movement_lifecycle_action(action):
        return movement_lifecycle_action_allowed(
            action,
            movement,
            exclude_log_id=exclude_log_id,
        )

    return stage_allows_generic_audit(movement, exclude_log_id=exclude_log_id)


def stage_allows_generic_audit(movement, *, exclude_log_id=None) -> bool:
    stage = derive_movement_execution_stage(movement, exclude_log_id=exclude_log_id)
    return stage not in (STAGE_COMPLETED, STAGE_CANCELLED)
