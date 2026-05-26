"""
mobile_api/dashboard/projections/workflow_projection.py

Read-only workflow projection for the driver dashboard.

Delegates allowed-action membership to ``operation_execution.get_allowed_actions``
and UI metadata to ``project_allowed_actions_payload`` — no duplicated rules.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.execution_stage_deriver import (
    derive_job_execution_stage,
)
from iroad_tenants.services.operation_execution_service import (
    OperationExecutionService,
)

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.dto.workflow_projection_input import (
    WorkflowProjectionInput,
)

_EMPTY_WORKFLOW: dict[str, Any] = {
    'current_stage': '',
    'next_action': {},
    'primary_action': {},
    'allowed_actions': [],
    'workflow_source': '',
}


def build_workflow_projection(
    *,
    request: Any | None = None,
    booking: Any | None = None,
    shipment: Any | None = None,
    movement: Any | None = None,
    booking_item_type: str = '',
    job_type: str = '',
    job_id: str = '',
    job_no: str = '',
) -> dict[str, Any]:
    """
    Build the dashboard ``workflow`` block for one operational entity.

    Shipment context takes precedence when ``shipment`` is set; otherwise
    movement-only (empty move) workflow is derived.
    """
    if shipment is None and movement is None:
        return dict(_EMPTY_WORKFLOW)

    if shipment is not None:
        return build_shipment_workflow(
            shipment,
            booking=booking,
            request=request,
            booking_item_type=booking_item_type or _shipment_line_type(shipment),
        )

    return build_empty_move_workflow(
        movement,
        request=request,
        job_id=job_id,
        job_no=job_no,
    )


def build_workflow_from_input(
    workflow_input: WorkflowProjectionInput,
) -> dict[str, Any]:
    """Build workflow from ``WorkflowProjectionInput``."""
    return build_workflow_projection(
        request=workflow_input.request,
        booking=workflow_input.booking,
        shipment=workflow_input.shipment,
        movement=workflow_input.movement,
        booking_item_type=workflow_input.booking_item_type,
        job_type=workflow_input.job_type,
        job_id=workflow_input.job_id,
        job_no=workflow_input.job_no,
    )


def build_workflow_for_dashboard_context(
    context: DriverDashboardContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Resolve workflow for orchestration context.

    Priority: active shipment (current job) → active empty move → empty block.
    """
    if context.active_shipment is not None:
        wf = build_shipment_workflow(
            context.active_shipment,
            booking=context.active_booking,
            request=request,
        )
    elif context.active_empty_movement is not None:
        wf = build_empty_move_workflow(
            context.active_empty_movement,
            request=request,
        )
    else:
        wf = dict(_EMPTY_WORKFLOW)

    if context.reconciliation:
        from mobile_api.dashboard.services.dashboard_status_reconciler import (
            workflow_reconciliation_extras,
        )

        wf.setdefault('workflow_metadata', {})['reconciliation'] = (
            workflow_reconciliation_extras(context)
        )
    return wf


def build_workflow_from_booking_selection(
    selection: DriverBookingSelectionResult,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Workflow for the current booking job card."""
    shipment = selection.active_shipment
    if shipment is None:
        return dict(_EMPTY_WORKFLOW)
    return build_shipment_workflow(
        shipment,
        booking=selection.booking,
        request=request,
    )


def build_workflow_from_empty_move_selection(
    selection: DriverEmptyMoveSelectionResult,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Workflow for ``current_empty_move``."""
    return build_empty_move_workflow(
        selection.movement,
        request=request,
    )


def build_shipment_workflow(
    shipment: Any,
    *,
    booking: Any | None = None,
    request: Any | None = None,
    booking_item_type: str = '',
) -> dict[str, Any]:
    """Shipment-bound workflow (laden job / round-trip leg)."""
    if shipment is None:
        return dict(_EMPTY_WORKFLOW)

    line_type = (booking_item_type or _shipment_line_type(shipment)).strip()
    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)
    engine_payload = OperationExecutionService.get_allowed_driver_actions(
        booking=booking,
        shipment=shipment,
        movement=None,
        booking_item_type=line_type,
        request=request,
        job_type='shipment',
        job_id=str(shipment_id) if shipment_id is not None else '',
        job_no=str(getattr(shipment, 'shipment_no', '') or ''),
    )
    stage_block = derive_job_execution_stage(shipment=shipment)
    return _map_engine_payload_to_dashboard(
        engine_payload,
        stage_block=stage_block,
        entity_type='shipment',
    )


def build_empty_move_workflow(
    movement: Any,
    *,
    request: Any | None = None,
    job_id: str = '',
    job_no: str = '',
) -> dict[str, Any]:
    """Movement-only workflow (empty move)."""
    if movement is None:
        return dict(_EMPTY_WORKFLOW)

    movement_id = getattr(movement, 'movement_id', None) or getattr(movement, 'pk', None)
    engine_payload = OperationExecutionService.get_allowed_driver_actions(
        booking=None,
        shipment=None,
        movement=movement,
        request=request,
        job_type='movement',
        job_id=job_id or (str(movement_id) if movement_id is not None else ''),
        job_no=job_no or str(getattr(movement, 'movement_no', '') or ''),
    )
    stage_block = derive_job_execution_stage(movement=movement)
    return _map_engine_payload_to_dashboard(
        engine_payload,
        stage_block=stage_block,
        entity_type='movement',
    )


def _map_engine_payload_to_dashboard(
    engine_payload: dict[str, Any],
    *,
    stage_block: dict[str, Any] | None = None,
    entity_type: str = '',
) -> dict[str, Any]:
    """
    Map ``OperationExecutionService.get_allowed_driver_actions`` output to the
    dashboard workflow contract.
    """
    actions = list(engine_payload.get('actions') or [])
    primary = engine_payload.get('primary_action') or {}
    primary_dict = dict(primary) if isinstance(primary, dict) else {}
    next_action = dict(primary_dict) if primary_dict else (dict(actions[0]) if actions else {})

    current_stage = (engine_payload.get('current_stage') or '').strip()
    if not current_stage and stage_block:
        current_stage = (stage_block.get('operational_stage') or '').strip() or (
            stage_block.get('execution_sub_stage') or ''
        )

    workflow: dict[str, Any] = {
        'current_stage': current_stage,
        'next_action': next_action,
        'primary_action': primary_dict,
        'allowed_actions': actions,
        'workflow_source': (
            engine_payload.get('workflow_source')
            or 'operation_execution.get_allowed_actions'
        ),
    }
    if stage_block or entity_type:
        workflow['workflow_metadata'] = _build_workflow_metadata(
            engine_payload,
            stage_block=stage_block or {},
            entity_type=entity_type,
        )
    return workflow


def _build_workflow_metadata(
    engine_payload: dict[str, Any],
    *,
    stage_block: dict[str, Any],
    entity_type: str,
) -> dict[str, Any]:
    """Non-breaking extras for clients that need stage / context diagnostics."""
    return {
        'entity_type': entity_type or stage_block.get('entity_type') or '',
        'execution_sub_stage': stage_block.get('execution_sub_stage') or '',
        'operational_stage': stage_block.get('operational_stage') or '',
        'status_for_workflow': stage_block.get('status_for_workflow') or '',
        'context_label': engine_payload.get('context_label') or '',
        'job_type': engine_payload.get('job_type') or '',
        'job_id': engine_payload.get('job_id') or '',
        'job_no': engine_payload.get('job_no') or '',
        'allowed_action_count': int(engine_payload.get('count') or 0),
    }


def _shipment_line_type(shipment: Any) -> str:
    return str(getattr(shipment, 'booking_item_type', '') or '').strip()


# Backward-compatible alias for skeleton callers.
def build_workflow_block(
    *,
    tenant_schema: str = '',
    booking: Any | None = None,
    shipment: Any | None = None,
    movement: Any | None = None,
    driver: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    _ = (tenant_schema, driver)
    return build_workflow_projection(
        request=request,
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=_shipment_line_type(shipment) if shipment else '',
    )
