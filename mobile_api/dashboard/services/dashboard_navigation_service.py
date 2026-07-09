"""
mobile_api/dashboard/services/dashboard_navigation_service.py

Driver-facing navigation hints for dashboard polling (resume active empty move).
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from tenant_workspace.models import TenantTruckMovementLog
from mobile_api.utils.next_action_hint_builder import (
    align_next_action_hint_with_workflow,
    build_next_action_hint,
)


def _movement_job_pointer(movement: Any) -> dict[str, str]:
    movement_id = getattr(movement, 'movement_id', None) or getattr(movement, 'pk', None)
    return {
        'job_type': 'movement',
        'job_id': str(movement_id or ''),
        'job_no': str(getattr(movement, 'movement_no', '') or ''),
        'entity_type': 'movement',
    }


def _enrich_movement_hint(
    hint: dict[str, Any],
    *,
    movement: Any,
    resume_existing: bool = False,
) -> dict[str, Any]:
    out = dict(hint)
    pointer = _movement_job_pointer(movement)
    out.update(pointer)
    if resume_existing:
        out['resume_existing_movement'] = True
        out.setdefault(
            'reason',
            'An empty move is already in progress. Continue that job.',
        )
    return out


def _movement_still_executable(
    movement: Any,
    *,
    selection: Any | None = None,
) -> bool:
    """
    Lightweight active check for payload assembly (no DB).

    ``active_empty_movement`` is already filtered inside ``schema_context``;
  this only guards stale in-memory rows using column status / derived stage.
    """
    status = (getattr(movement, 'status', '') or '').strip()
    if status in {
        TenantTruckMovementLog.Status.COMPLETED,
        TenantTruckMovementLog.Status.CANCELLED,
    }:
        return False
    stage = ''
    if selection is not None:
        stage = (getattr(selection, 'movement_stage', '') or '').strip().casefold()
    if stage in {'completed', 'cancelled'}:
        return False
    return True


def _resolve_executable_empty_move(context: DriverDashboardContext) -> Any | None:
    """
    Movement pointer for on-call resume only when still executable.

    After End Job (``complete_done`` or column ``Completed``), the movement is
    closed and must not block creating a new empty move.
    """
    movement = context.active_empty_movement
    if movement is None:
        return None
    if not _movement_still_executable(
        movement,
        selection=context.empty_move_selection,
    ):
        return None
    return movement


def build_dashboard_on_call_state(context: DriverDashboardContext) -> dict[str, Any]:
    """
    On-call / empty-move gate for the mobile home screen.

    When an active empty move exists and no laden shipment is in progress,
    creation must be blocked and the client should open the existing movement.
    After End Job closes the movement, ``can_create_empty_move`` becomes true.
    """
    movement = _resolve_executable_empty_move(context)
    has_laden_job = context.active_shipment is not None
    has_booking_job = context.active_booking is not None and not has_laden_job

    if movement is None:
        can_create = not has_laden_job and not has_booking_job
        return {
            'empty_move_active': False,
            'can_create_empty_move': can_create,
        }

    pointer = _movement_job_pointer(movement)
    blocked_by_other_job = has_laden_job or has_booking_job
    return {
        'empty_move_active': True,
        'can_create_empty_move': False,
        'blocked_by_active_job': blocked_by_other_job,
        'resume_job': pointer,
        **pointer,
    }


def build_dashboard_next_action_hint(
    context: DriverDashboardContext,
    *,
    workflow: dict[str, Any],
    request: Any | None = None,
) -> dict[str, Any]:
    """Align dashboard polling with Job Detail navigation for empty moves."""
    _ = request
    movement = _resolve_executable_empty_move(context)
    if movement is None:
        return {}

    pod_cod = dict(context.pod_cod_projection or {})
    if context.active_shipment is not None:
        return {}

    tenant_schema = (getattr(context, 'tenant_schema', None) or '').strip()
    hint = build_next_action_hint(
        workflow=workflow,
        pod_cod=pod_cod,
        movement=movement,
        driver=context.driver,
        tenant_schema=tenant_schema,
    )
    hint = align_next_action_hint_with_workflow(
        hint,
        workflow,
        pod_cod,
        tenant_schema=tenant_schema,
        driver=context.driver,
    )
    return _enrich_movement_hint(hint, movement=movement, resume_existing=True)
