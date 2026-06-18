"""
mobile_api/job_detail/projections/workflow_projection.py

``workflow`` section — Action-Master-driven stage, allowed actions, requirements.

Allowed-action **membership** only from ``get_allowed_actions`` (via
``OperationExecutionService``). Stage uses reconciled log-primary state when available.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_execution import _is_hard_copy_collection_action
from iroad_tenants.operation_runtime.execution_stage_deriver import (
    derive_job_execution_stage,
)
from iroad_tenants.services.operation_execution_service import (
    OperationExecutionService,
)

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.helpers.booking_job_context import (
    resolve_booking_job_execution_context,
)
from mobile_api.job_detail.services.job_detail_projection_cache import (
    get_projection_cache,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    apply_reconciled_status_overlays,
    authoritative_entity_status,
    entity_reconciliation_block,
)

_EMPTY_WORKFLOW: dict[str, Any] = {
    'current_stage': '',
    'next_action': {},
    'primary_action': {},
    'allowed_actions': [],
    'workflow_source': '',
    'workflow_integrity': {},
    'reconciliation': {},
}


def build_workflow_section(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Build Job Detail ``workflow`` for shipment or movement explicit scope.

    Requires ``context.reconciliation`` populated first (log-primary reconcile).
    """
    if context.job_type == 'shipment' and context.shipment is None:
        return dict(_EMPTY_WORKFLOW)
    if context.job_type == 'movement' and context.movement is None:
        return dict(_EMPTY_WORKFLOW)
    if context.job_type == 'booking' and context.booking is None:
        return dict(_EMPTY_WORKFLOW)

    recon_block = entity_reconciliation_block(context)
    top_integrity = dict((context.reconciliation or {}).get('workflow_integrity') or {})
    reconciliation_out = _reconciliation_api_slice(recon_block)

    cache = get_projection_cache(context)
    prefetched = None
    if cache is not None:
        prefetched = (
            cache.shipment_logs
            if context.job_type == 'shipment'
            else cache.booking_logs
            if context.job_type == 'booking'
            else cache.movement_logs
        )
    auth_status = authoritative_entity_status(context)

    with apply_reconciled_status_overlays(context):
        if context.job_type == 'shipment':
            workflow = _build_shipment_workflow(
                context,
                request=request,
                authoritative_status=auth_status,
                prefetched_logs=prefetched,
            )
        elif context.job_type == 'booking':
            workflow = _build_booking_workflow(context, request=request)
        else:
            workflow = _build_movement_workflow(
                context,
                request=request,
                prefetched_logs=prefetched,
            )

    workflow['workflow_integrity'] = top_integrity or dict(
        recon_block.get('workflow_integrity') or {}
    )
    workflow['reconciliation'] = reconciliation_out
    return workflow


def _build_shipment_workflow(
    context: JobDetailContext,
    *,
    request: Any | None,
    authoritative_status: str,
    prefetched_logs: list | None,
) -> dict[str, Any]:
    shipment = context.shipment
    booking = context.booking
    line_type = _shipment_line_type(shipment)
    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)

    stage_block = derive_job_execution_stage(
        shipment=shipment,
        authoritative_shipment_status=authoritative_status or None,
        prefetched_logs=prefetched_logs,
    )

    engine_payload = OperationExecutionService.get_allowed_driver_actions(
        booking=booking,
        shipment=shipment,
        movement=None,
        booking_item_type=line_type,
        request=request,
        job_type='shipment',
        job_id=str(shipment_id) if shipment_id is not None else context.job_id,
        job_no=str(getattr(shipment, 'shipment_no', '') or ''),
    )
    workflow = _map_engine_payload(
        engine_payload,
        stage_block=stage_block,
        entity_type='shipment',
    )
    return _strip_hard_copy_from_driver_workflow(workflow)


def _build_booking_workflow(
    context: JobDetailContext,
    *,
    request: Any | None,
) -> dict[str, Any]:
    """Booking-only workflow before Auto Shipment creates the first leg."""
    booking = context.booking
    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    exec_ctx = resolve_booking_job_execution_context(context)
    booking_item_type = str(exec_ctx.get('booking_item_type') or '').strip()
    stage_block = {
        'entity_type': 'booking',
        'operational_stage': '',
        'execution_sub_stage': '',
        'status_for_workflow': str(getattr(booking, 'booking_status', '') or ''),
    }
    if exec_ctx.get('booking_execution_stage'):
        stage_block['execution_sub_stage'] = exec_ctx['booking_execution_stage']
    engine_payload = OperationExecutionService.get_allowed_driver_actions(
        booking=booking,
        shipment=None,
        movement=None,
        booking_item_type=booking_item_type,
        request=request,
        job_type='booking',
        job_id=str(booking_id) if booking_id is not None else context.job_id,
        job_no=str(getattr(booking, 'booking_no', '') or ''),
    )
    workflow = _map_engine_payload(
        engine_payload,
        stage_block=stage_block,
        entity_type='booking',
    )
    if booking_item_type:
        workflow['booking_item_type'] = booking_item_type
    if exec_ctx.get('backload_bootstrap'):
        workflow['backload_bootstrap_pending'] = True
    return workflow


def _build_movement_workflow(
    context: JobDetailContext,
    *,
    request: Any | None,
    prefetched_logs: list | None,
) -> dict[str, Any]:
    movement = context.movement
    movement_id = getattr(movement, 'movement_id', None) or getattr(movement, 'pk', None)

    stage_block = derive_job_execution_stage(movement=movement)
    _ = prefetched_logs

    engine_payload = OperationExecutionService.get_allowed_driver_actions(
        booking=None,
        shipment=None,
        movement=movement,
        request=request,
        job_type='movement',
        job_id=str(movement_id) if movement_id is not None else context.job_id,
        job_no=str(getattr(movement, 'movement_no', '') or ''),
    )
    return _map_engine_payload(
        engine_payload,
        stage_block=stage_block,
        entity_type='movement',
    )


def _map_engine_payload(
    engine_payload: dict[str, Any],
    *,
    stage_block: dict[str, Any] | None = None,
    entity_type: str = '',
) -> dict[str, Any]:
    """Map engine output to Job Detail workflow contract (includes execution_requirements)."""
    actions = list(engine_payload.get('actions') or [])
    primary = engine_payload.get('primary_action') or {}
    primary_dict = dict(primary) if isinstance(primary, dict) else {}
    next_action = (
        dict(primary_dict) if primary_dict else (dict(actions[0]) if actions else {})
    )

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
        'workflow_integrity': {},
        'reconciliation': {},
    }
    if stage_block or entity_type:
        workflow['workflow_metadata'] = {
            'entity_type': entity_type or (stage_block or {}).get('entity_type') or '',
            'execution_sub_stage': (stage_block or {}).get('execution_sub_stage') or '',
            'operational_stage': (stage_block or {}).get('operational_stage') or '',
            'status_for_workflow': (stage_block or {}).get('status_for_workflow') or '',
            'context_label': engine_payload.get('context_label') or '',
            'job_type': engine_payload.get('job_type') or '',
            'job_id': engine_payload.get('job_id') or '',
            'job_no': engine_payload.get('job_no') or '',
            'allowed_action_count': int(engine_payload.get('count') or 0),
        }
    return workflow


def _strip_hard_copy_from_driver_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    """Hard POD (A7H) is completed inside Upload POD — not a separate workflow row."""
    out = dict(workflow or {})
    actions = [
        row
        for row in (out.get('allowed_actions') or [])
        if not _is_hard_copy_collection_action_row(row)
    ]
    out['allowed_actions'] = actions
    for key in ('next_action', 'primary_action'):
        row = dict(out.get(key) or {})
        if _is_hard_copy_collection_action_row(row):
            out[key] = dict(actions[0]) if actions else {}
    return out


def _is_hard_copy_collection_action_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    code = str(row.get('action_code') or '').strip()
    if code.upper() == 'A7H':
        return True
    requirements = row.get('execution_requirements') or {}
    return bool(requirements.get('hard_copy_collection'))


def _reconciliation_api_slice(block: dict[str, Any]) -> dict[str, Any]:
    """Public reconciliation subset for the workflow block."""
    if not block:
        return {
            'authoritative_status': '',
            'column_status': '',
            'status_source': 'none',
            'drift_detected': False,
            'drift_reason': '',
        }
    return {
        'authoritative_status': (block.get('authoritative_status') or '').strip(),
        'column_status': (block.get('column_status') or '').strip(),
        'status_source': (block.get('status_source') or '').strip(),
        'drift_detected': bool(block.get('drift_detected')),
        'drift_reason': (block.get('drift_reason') or '').strip(),
    }


def _shipment_line_type(shipment: Any) -> str:
    return str(getattr(shipment, 'booking_item_type', '') or '').strip()
