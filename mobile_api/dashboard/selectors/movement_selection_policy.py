"""
mobile_api/dashboard/selectors/movement_selection_policy.py

Pure empty-move selection rules for the driver dashboard.

Reuses ``is_empty_movement`` and stage derivation from
``iroad_tenants.operation_runtime``.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from tenant_workspace.models import TenantTruckMovementLog

from iroad_tenants.operation_runtime.movement_action_validator import (
    is_empty_movement,
)
from iroad_tenants.operation_runtime.movement_stage_derivation import (
    derive_movement_execution_stage,
    derive_movement_operational_stage,
    movement_log_milestone_flags,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    STAGE_ARRIVED,
    STAGE_CANCELLED,
    STAGE_COMPLETED,
    STAGE_CREATED,
    STAGE_IN_TRANSIT,
    STAGE_STARTED,
    execution_stage_label,
    is_terminal_movement_status,
)

# Dashboard progress weights by execution sub-stage.
_STAGE_PROGRESS: dict[str, int] = {
    STAGE_CREATED: 10,
    STAGE_STARTED: 30,
    STAGE_IN_TRANSIT: 55,
    STAGE_ARRIVED: 85,
    STAGE_COMPLETED: 100,
    STAGE_CANCELLED: 0,
}


def is_movement_completed(movement: Any) -> bool:
    return (movement.status or '').strip() == TenantTruckMovementLog.Status.COMPLETED


def is_movement_cancelled(movement: Any) -> bool:
    return (movement.status or '').strip() == TenantTruckMovementLog.Status.CANCELLED


def is_active_empty_move(movement: Any) -> bool:
    """Empty move that is still executable on the dashboard."""
    if movement is None:
        return False
    if not is_empty_movement(movement):
        return False
    if is_shipment_linked_loaded_movement(movement):
        return False
    if is_movement_completed(movement) or is_movement_cancelled(movement):
        return False
    if is_terminal_movement_status((movement.status or '').strip()):
        return False
    return True


def is_shipment_linked_loaded_movement(movement: Any) -> bool:
    """
    Laden / shipment-born movements — excluded from ``current_empty_move``.

    Matches ``birth_movement_for_shipment`` (``movement_source='Loaded'`` + shipment FK).
    """
    if movement is None:
        return False
    if getattr(movement, 'shipment_id', None):
        return True
    source = str(getattr(movement, 'movement_source', '') or '').strip().casefold()
    return source == 'loaded'


def driver_assigned_to_movement(driver: Any, movement: Any) -> bool:
    driver_pk = driver_pk_value(driver)
    if driver_pk is None:
        return False
    return getattr(movement, 'driver_id', None) == driver_pk


def movement_sort_key(movement: Any) -> tuple:
    """Earlier movement_date / sequence first (current job ordering)."""
    movement_date = getattr(movement, 'movement_date', None)
    return (
        movement_date or '',
        int(getattr(movement, 'movement_sequence', 0) or 0),
        str(getattr(movement, 'movement_no', '') or ''),
    )


def sorted_movements(movements: Iterable[Any]) -> list[Any]:
    return sorted(movements, key=movement_sort_key)


def movement_execution_stage(movement: Any) -> str:
    return derive_movement_execution_stage(movement)


def movement_operational_stage(movement: Any) -> str:
    return derive_movement_operational_stage(movement)


def movement_progress_percentage(movement: Any) -> int:
    """
    Progress from execution sub-stage + milestone flags.

    Uses runtime derivation first; bumps within ``In Progress`` when logs
  advance milestones before column status catches up.
    """
    stage = movement_execution_stage(movement)
    base = _STAGE_PROGRESS.get(stage, 0)
    if stage in (STAGE_COMPLETED, STAGE_CANCELLED):
        return base

    flags = movement_log_milestone_flags(movement)
    if flags.get('complete_done'):
        return 100
    if flags.get('arrived_done') or stage == STAGE_ARRIVED:
        return max(base, _STAGE_PROGRESS[STAGE_ARRIVED])
    if flags.get('in_transit_done') or stage == STAGE_IN_TRANSIT:
        return max(base, _STAGE_PROGRESS[STAGE_IN_TRANSIT])
    if flags.get('start_done') or stage == STAGE_STARTED:
        return max(base, _STAGE_PROGRESS[STAGE_STARTED])
    return base


def build_movement_summary(movement: Any) -> dict[str, Any]:
    """Read-only movement summary for dashboard orchestration."""
    if movement is None:
        return {}

    stage = movement_execution_stage(movement)
    return {
        'movement_id': str(getattr(movement, 'movement_id', None) or movement.pk or ''),
        'movement_no': str(getattr(movement, 'movement_no', '') or ''),
        'movement_stage': stage,
        'movement_stage_label': execution_stage_label(stage) or movement_operational_stage(movement),
        'movement_status': str(getattr(movement, 'status', '') or ''),
        'operational_stage': movement_operational_stage(movement),
        'progress_percentage': movement_progress_percentage(movement),
        'movement_source': str(getattr(movement, 'movement_source', '') or ''),
        'empty_move_reason': str(getattr(movement, 'empty_move_reason', '') or ''),
        'movement_date': str(getattr(movement, 'movement_date', '') or ''),
        'is_empty_move': is_empty_movement(movement),
    }


def passes_booking_exclusion(
    movement: Any,
    *,
    exclude_booking_id: Any | None,
) -> bool:
    """When a laden booking is active, skip empty moves tied to that booking."""
    if exclude_booking_id is None:
        return True
    movement_booking_id = getattr(movement, 'booking_id', None)
    if movement_booking_id is None:
        return True
    return str(movement_booking_id) != str(exclude_booking_id)


def select_active_empty_move_from_list(
    driver: Any,
    movements: Sequence[Any],
    *,
    exclude_booking_id: Any | None = None,
) -> Any | None:
    """Pick the current empty move from an in-memory sequence (tests / prefetch)."""
    for movement in sorted_movements(movements):
        if not is_active_empty_move(movement):
            continue
        if not driver_assigned_to_movement(driver, movement):
            continue
        if not passes_booking_exclusion(movement, exclude_booking_id=exclude_booking_id):
            continue
        return movement
    return None


def driver_pk_value(driver: Any) -> Any:
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
