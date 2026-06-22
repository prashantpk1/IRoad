"""
Movement column status forward graph (TenantTruckMovementLog.status).

User-facing execution stages (Created → Started → …) are derived in
``movement_stage_derivation`` from status + append-only action logs.
"""

from __future__ import annotations

from tenant_workspace.models import TenantTruckMovementLog
from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_movement_status_impact,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_pickup_or_loading_action,
)

# Execution-stage taxonomy (mobile / reporting).
STAGE_CREATED = 'created'
STAGE_STARTED = 'started'
STAGE_IN_TRANSIT = 'in_transit'
STAGE_ARRIVED = 'arrived'
STAGE_COMPLETED = 'completed'
STAGE_CANCELLED = 'cancelled'

MOVEMENT_COLUMN_SCHEDULED = TenantTruckMovementLog.Status.SCHEDULED

_MOVEMENT_STATUS_RANK = {
    TenantTruckMovementLog.Status.SCHEDULED: 10,
    TenantTruckMovementLog.Status.IN_PROGRESS: 20,
    TenantTruckMovementLog.Status.COMPLETED: 70,
    TenantTruckMovementLog.Status.CANCELLED: 99,
}

_TERMINAL_MOVEMENT_STATUSES = {
    TenantTruckMovementLog.Status.COMPLETED,
    TenantTruckMovementLog.Status.CANCELLED,
}

# Forward transitions via Action Master ``movement_status_impact``.
_MOVEMENT_FORWARD_FROM = {
    TenantTruckMovementLog.Status.IN_PROGRESS: {
        TenantTruckMovementLog.Status.SCHEDULED,
    },
    TenantTruckMovementLog.Status.COMPLETED: {
        TenantTruckMovementLog.Status.IN_PROGRESS,
        TenantTruckMovementLog.Status.SCHEDULED,
    },
    TenantTruckMovementLog.Status.CANCELLED: {
        TenantTruckMovementLog.Status.SCHEDULED,
        TenantTruckMovementLog.Status.IN_PROGRESS,
    },
}

_STAGE_LABELS = {
    STAGE_CREATED: 'Created',
    STAGE_STARTED: 'Started',
    STAGE_IN_TRANSIT: 'In Transit',
    STAGE_ARRIVED: 'Arrived',
    STAGE_COMPLETED: 'Completed',
    STAGE_CANCELLED: 'Cancelled',
}


def movement_status_rank(status: str) -> int:
    return _MOVEMENT_STATUS_RANK.get(status or '', 0)


def is_terminal_movement_status(status: str) -> bool:
    return (status or '') in _TERMINAL_MOVEMENT_STATUSES


def movement_impact_allowed_from_current(*, current: str, impact_status: str) -> bool:
    """Whether ``impact_status`` may be applied from ``current`` column value."""
    if not impact_status:
        return False
    allowed_from = _MOVEMENT_FORWARD_FROM.get(impact_status, set())
    if not allowed_from:
        return False
    if current not in allowed_from:
        return False
    target_rank = movement_status_rank(impact_status)
    current_rank = movement_status_rank(current)
    return target_rank > current_rank


def resolve_action_movement_impact(action) -> str | None:
    if action is None:
        return None
    return resolve_movement_status_impact((action.movement_status_impact or '').strip())


def execution_stage_label(stage: str) -> str:
    if not stage:
        return ''
    return _STAGE_LABELS.get(stage, stage.replace('_', ' ').title())


def is_movement_cancel_action(action) -> bool:
    return operation_action_matches(
        action,
        'cancel movement',
        'cancel move',
        'cancel empty',
    ) or resolve_action_movement_impact(action) == TenantTruckMovementLog.Status.CANCELLED


def is_movement_start_action(action) -> bool:
    impact = resolve_action_movement_impact(action)
    if impact == TenantTruckMovementLog.Status.IN_PROGRESS:
        return True
    return operation_action_matches(
        action,
        'start movement',
        'start move',
        'start empty',
        'begin movement',
        'm1',
        'em1',
    )


def is_movement_in_transit_action(action) -> bool:
    return operation_action_matches(
        action,
        'in transit',
        'en route',
        'depart',
        'm2',
        'em2',
        'movement depart',
    ) and not operation_action_matches(action, 'pickup', 'a2', 'shipment')


def is_movement_arrived_action(action) -> bool:
    return operation_action_matches(
        action,
        'arrived',
        'arrival at',
        'reach destination',
        'm3',
        'em3',
    ) and not is_pickup_or_loading_action(action)


def is_movement_complete_action(action) -> bool:
    impact = resolve_action_movement_impact(action)
    if impact == TenantTruckMovementLog.Status.COMPLETED:
        return True
    return operation_action_matches(
        action,
        'complete movement',
        'complete move',
        'end movement',
        'finish movement',
        'm4',
        'em4',
    )


def is_movement_lifecycle_action(action) -> bool:
    return (
        is_movement_start_action(action)
        or is_movement_in_transit_action(action)
        or is_movement_arrived_action(action)
        or is_movement_complete_action(action)
        or is_movement_cancel_action(action)
    )
