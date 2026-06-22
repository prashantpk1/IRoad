"""
Movement-only workflow engine facade (empty move + movement job detail).

Append-only action logs, forward graph, dedupe, and stage derivation.
"""

from __future__ import annotations

from tenant_workspace.models import TenantOperationAction, TenantOperationActionLog
from iroad_tenants.operation_runtime.movement_action_validator import (
    is_movement_only_context,
    movement_action_is_allowed,
)
from iroad_tenants.operation_runtime.movement_stage_derivation import (
    derive_movement_execution_stage,
    derive_movement_latest_execution_state,
    derive_movement_operational_stage,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    execution_stage_label,
)


def movement_executed_action_ids(
    movement,
    *,
    exclude_log_id=None,
) -> set:
    if movement is None:
        return set()
    qs = TenantOperationActionLog.objects.exclude(operation_action__isnull=True)
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    qs = qs.filter(truck_movement_id=movement.pk)
    return set(qs.values_list('operation_action_id', flat=True))


def movement_executed_action_codes(
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


def movement_action_allowed(
    action,
    *,
    movement,
    exclude_log_id=None,
    include_action_id=None,
) -> bool:
    if action is None or movement is None:
        return False
    if include_action_id and str(action.action_id) == str(include_action_id):
        return True
    if action.status != TenantOperationAction.Status.ACTIVE:
        return False
    executed = movement_executed_action_ids(
        movement,
        exclude_log_id=exclude_log_id,
    )
    return movement_action_is_allowed(
        action,
        movement,
        exclude_log_id=exclude_log_id,
        executed_action_ids=executed,
    )


def validate_movement_action_allowed(
    operation_action,
    *,
    movement,
    exclude_log_id=None,
    previous_action_id=None,
) -> str | None:
    """Return error message when disallowed; None when OK."""
    if operation_action is None:
        return 'Invalid operation action selected.'
    include_id = None
    if previous_action_id and operation_action.pk == previous_action_id:
        include_id = previous_action_id
    if movement_action_allowed(
        operation_action,
        movement=movement,
        exclude_log_id=exclude_log_id,
        include_action_id=include_id,
    ):
        return None
    stage = derive_movement_execution_stage(movement, exclude_log_id=exclude_log_id)
    label = execution_stage_label(stage) or (movement.status if movement else '')
    return (
        f'Action "{operation_action.english_label or operation_action.action_code}" '
        f'is not allowed when movement execution stage is {label}. '
        f'Complete the prior movement step or choose an action configured for empty moves.'
    )


def movement_allowed_actions_context_label(movement) -> str:
    if movement is None:
        return 'Select a movement to see allowed actions.'
    stage = derive_movement_operational_stage(movement)
    return f'Allowed actions for movement execution stage: {stage}'


def filter_movement_allowed_actions(
    actions,
    *,
    movement,
    exclude_log_id=None,
    include_action_id=None,
):
    from iroad_tenants.operation_runtime.allowed_actions_query import (
        prefilter_allowed_action_candidates,
    )

    executed = movement_executed_action_ids(
        movement,
        exclude_log_id=exclude_log_id,
    )
    if hasattr(actions, 'filter'):
        base = actions
    else:
        from tenant_workspace.models import TenantOperationAction

        base = TenantOperationAction.objects.filter(
            pk__in=[a.pk for a in actions],
        )
    candidates = prefilter_allowed_action_candidates(
        shipment=None,
        movement=movement,
        executed_action_ids=executed,
        exclude_log_id=exclude_log_id,
    )
    if hasattr(actions, 'filter'):
        candidates = candidates.filter(
            pk__in=base.values_list('pk', flat=True),
        )
    return [
        action
        for action in candidates
        if movement_action_allowed(
            action,
            movement=movement,
            exclude_log_id=exclude_log_id,
            include_action_id=include_action_id,
        )
    ]


__all__ = [
    'derive_movement_execution_stage',
    'derive_movement_latest_execution_state',
    'derive_movement_operational_stage',
    'is_movement_only_context',
    'movement_action_allowed',
    'movement_executed_action_ids',
    'validate_movement_action_allowed',
    'movement_allowed_actions_context_label',
    'filter_movement_allowed_actions',
]
