"""
Unified execution-stage derivation (shipment + movement) from logs-first state.
"""

from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.movement_stage_derivation import (
    derive_movement_execution_stage,
    derive_movement_operational_stage,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    is_terminal_movement_status,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    STAGE_PICKUP,
    STAGE_LOADING,
    STAGE_PRE_TRANSIT,
    derive_shipment_execution_stage,
    execution_stage_operational_label,
)


_EARLY_SUB_STAGES = frozenset({STAGE_PICKUP, STAGE_LOADING, STAGE_PRE_TRANSIT})


def derive_shipment_execution_stage_from_state(
    shipment,
    *,
    authoritative_status: str | None = None,
    exclude_log_id=None,
    prefetched_logs=None,
) -> str:
    """
    Sub-stage from logs; uses authoritative log status for mid/late lifecycle mapping.
    """
    if shipment is None:
        return ''

    sub_stage = derive_shipment_execution_stage(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    if sub_stage in _EARLY_SUB_STAGES:
        return sub_stage

    status_for_mapping = (authoritative_status or '').strip() or (
        shipment.shipment_status or ''
    )
    if status_for_mapping != (shipment.shipment_status or '').strip():
        return derive_shipment_execution_stage(
            shipment,
            exclude_log_id=exclude_log_id,
            status_for_stage=status_for_mapping,
            prefetched_logs=prefetched_logs,
        )
    return sub_stage


def derive_shipment_operational_stage(
    shipment,
    *,
    authoritative_status: str | None = None,
    exclude_log_id=None,
    prefetched_logs=None,
) -> str:
    stage = derive_shipment_execution_stage_from_state(
        shipment,
        authoritative_status=authoritative_status,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    label = execution_stage_operational_label(stage)
    if label:
        return label
    return (authoritative_status or shipment.shipment_status or '').strip()


def derive_movement_execution_stage_from_state(
    movement,
    *,
    authoritative_status: str | None = None,
    exclude_log_id=None,
) -> str:
    """Sub-stage from logs; optional authoritative status overrides column cache."""
    if movement is None:
        return ''

    sub_stage = derive_movement_execution_stage(
        movement,
        exclude_log_id=exclude_log_id,
    )
    status_for_mapping = (authoritative_status or '').strip() or (movement.status or '')
    if status_for_mapping != (movement.status or '').strip():
        return derive_movement_execution_stage(
            movement,
            exclude_log_id=exclude_log_id,
            status_for_stage=status_for_mapping,
        )
    return sub_stage


def derive_movement_operational_stage_from_state(
    movement,
    *,
    authoritative_status: str | None = None,
    exclude_log_id=None,
) -> str:
    status_for_mapping = (authoritative_status or '').strip() or None
    label = derive_movement_operational_stage(
        movement,
        exclude_log_id=exclude_log_id,
        status_for_stage=status_for_mapping,
    )
    if label:
        return label
    return (authoritative_status or movement.status or '').strip()


def derive_job_execution_stage(
    *,
    shipment=None,
    movement=None,
    authoritative_shipment_status: str | None = None,
    authoritative_movement_status: str | None = None,
    exclude_log_id=None,
    prefetched_logs=None,
) -> dict[str, Any]:
    """Unified stage block for mobile job detail."""
    if shipment is not None:
        sub_stage = derive_shipment_execution_stage_from_state(
            shipment,
            authoritative_status=authoritative_shipment_status,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        )
        operational = derive_shipment_operational_stage(
            shipment,
            authoritative_status=authoritative_shipment_status,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        )
        return {
            'entity_type': 'shipment',
            'execution_sub_stage': sub_stage,
            'operational_stage': operational,
            'status_for_workflow': authoritative_shipment_status
            or shipment.shipment_status,
        }

    if movement is not None:
        workflow_status = (
            (authoritative_movement_status or '').strip()
            or (movement.status or '').strip()
        )
        sub_stage = derive_movement_execution_stage_from_state(
            movement,
            authoritative_status=workflow_status or None,
            exclude_log_id=exclude_log_id,
        )
        operational = derive_movement_operational_stage_from_state(
            movement,
            authoritative_status=workflow_status or None,
            exclude_log_id=exclude_log_id,
        )
        return {
            'entity_type': 'movement',
            'execution_sub_stage': sub_stage,
            'operational_stage': operational,
            'status_for_workflow': workflow_status,
        }

    return {
        'entity_type': '',
        'execution_sub_stage': '',
        'operational_stage': '',
        'status_for_workflow': '',
    }
