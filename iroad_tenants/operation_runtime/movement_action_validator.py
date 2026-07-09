"""
Movement-only action classification and allow/deny rules.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

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


def is_empty_move_catalog_action(action) -> bool:
    """True for tenant Action Master rows in the empty-move sequence category."""
    if action is None:
        return False
    cat = (getattr(action, 'sequence_category', None) or '').strip().casefold()
    return cat in {'empty_move', 'empty move'}


def empty_move_sequence_category_q() -> Q:
    """Django Q matching Action Master ``sequence_category`` empty-move variants."""
    return Q(sequence_category__iexact='empty_move') | Q(sequence_category__iexact='empty move')


def is_without_scope_catalog_action(action) -> bool:
    """True for tenant Operation Actions outside job / empty-move sequences."""
    if action is None:
        return False
    scope = str(getattr(action, 'action_scope', '') or '').strip().casefold()
    if scope == 'without':
        return True
    cat = str(getattr(action, 'sequence_category', '') or '').strip().casefold()
    return cat == 'without'


def is_on_call_catalog_action(action) -> bool:
    """True for tenant Operation Actions in On Call workflow scope."""
    if action is None:
        return False
    return str(getattr(action, 'action_scope', '') or '').strip().casefold() == 'on_call'


def is_standalone_execution_action(action) -> bool:
    """
    Actions recorded via Action Log outside the sequenced job/empty-move chain.

    Includes without-scope reversals (Incident Report, Cancel Shipment) and On Call rows.
    """
    return is_without_scope_catalog_action(action) or is_on_call_catalog_action(action)


def is_movement_only_context(*, shipment=None, movement=None) -> bool:
    """Policy uses movement engine when no shipment is on the action context."""
    return movement is not None and shipment is None


def action_applies_to_movement_context(action, *, empty_move: bool) -> bool:
    """Filter Action Master rows for movement-only execution."""
    if action is None:
        return False
    if empty_move and is_empty_move_catalog_action(action):
        return True
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


def _tenant_schema_for_empty_move_policy() -> str:
    try:
        from django.db import connection

        schema = str(getattr(connection, 'schema_name', '') or '').strip()
        if schema and schema != 'public':
            return schema
    except Exception:
        pass
    return ''


def _ordered_empty_move_catalog_actions() -> list[Any]:
    from mobile_api.helpers.empty_move_action_resolver import (
        list_empty_move_workflow_actions,
    )

    actions = list_empty_move_workflow_actions(_tenant_schema_for_empty_move_policy())
    return sorted(
        actions,
        key=lambda row: (
            int(getattr(row, 'sequence_number', 0) or 0),
            str(getattr(row, 'action_code', '') or ''),
        ),
    )


def _empty_move_action_sequence_index(action) -> int | None:
    action_id = str(getattr(action, 'action_id', '') or '').strip()
    action_code = str(getattr(action, 'action_code', '') or '').strip().casefold()
    ordered = _ordered_empty_move_catalog_actions()
    for index, row in enumerate(ordered):
        row_id = str(getattr(row, 'action_id', '') or '').strip()
        row_code = str(getattr(row, 'action_code', '') or '').strip().casefold()
        if action_id and row_id and action_id == row_id:
            return index
        if action_code and row_code and action_code == row_code:
            return index
    seq = int(getattr(action, 'sequence_number', 0) or 0)
    if seq > 0:
        for index, row in enumerate(ordered):
            if int(getattr(row, 'sequence_number', 0) or 0) == seq:
                return index
    return None


def empty_move_sequence_action_allowed(
    action,
    movement,
    *,
    exclude_log_id=None,
) -> bool | None:
    """
    Sequence-category policy for ``empty_move`` Action Master rows.

    Returns ``None`` when this action/movement pair is outside empty-move catalog scope.
    """
    if not is_empty_movement(movement) or not is_empty_move_catalog_action(action):
        return None

    ordered = _ordered_empty_move_catalog_actions()
    if not ordered:
        return None

    position = _empty_move_action_sequence_index(action)
    if position is None:
        return None

    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)
    stage = derive_movement_execution_stage(movement, exclude_log_id=exclude_log_id)
    total = len(ordered)

    if position == 0:
        return stage == STAGE_CREATED and not flags['start_done']

    if position == total - 1:
        if flags['complete_done']:
            return False
        if validate_movement_completion_stage(movement, exclude_log_id=exclude_log_id):
            return False
        return True

    if is_movement_arrived_action(action) or (
        total >= 4 and position == total - 2
    ):
        return flags['in_transit_done'] and not flags['arrived_done']

    return flags['start_done'] and not flags['in_transit_done']


def _empty_move_catalog_has_arrived_action() -> bool:
    """True when tenant empty-move workflow includes a distinct arrival step."""
    try:
        from django.db import connection

        schema = str(getattr(connection, 'schema_name', '') or '').strip()
        if not schema or schema == 'public':
            return True
        from mobile_api.helpers.empty_move_action_resolver import (
            list_empty_move_workflow_actions,
        )

        return any(
            is_movement_arrived_action(action)
            for action in list_empty_move_workflow_actions(schema)
        )
    except Exception:
        return True


def validate_movement_completion_stage(movement, *, exclude_log_id=None) -> str | None:
    stage = derive_movement_execution_stage(movement, exclude_log_id=exclude_log_id)
    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)
    if flags['complete_done'] or flags['arrived_done'] or stage == STAGE_ARRIVED:
        return None
    if (
        is_empty_movement(movement)
        and flags['in_transit_done']
        and not _empty_move_catalog_has_arrived_action()
    ):
        return None
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
    if is_empty_movement(movement) and is_empty_move_catalog_action(action):
        position = _empty_move_action_sequence_index(action)
        if position == 0:
            return True
    executed = _movement_executed_action_codes(
        movement,
        exclude_log_id=exclude_log_id,
    )
    if required.issubset(executed):
        return True
    if not is_empty_movement(movement):
        return False
    flags = movement_log_milestone_flags(movement, exclude_log_id=exclude_log_id)
    if is_movement_in_transit_action(action) and flags['start_done']:
        return True
    if is_movement_arrived_action(action) and flags['in_transit_done']:
        return True
    if is_movement_complete_action(action):
        if flags['arrived_done']:
            return True
        if flags['in_transit_done'] and not _empty_move_catalog_has_arrived_action():
            return True
    return False


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
    sequence_allowed = empty_move_sequence_action_allowed(
        action,
        movement,
        exclude_log_id=exclude_log_id,
    )
    if sequence_allowed is not None:
        return sequence_allowed

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
