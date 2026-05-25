"""
Wraps the existing Action Engine policy module (no rule changes).
"""

from __future__ import annotations

from typing import Any

from iroad_tenants.operation_execution import (
    action_options_payload,
    allowed_actions_context_label,
    get_allowed_actions,
    validate_operation_action_allowed,
)
from mobile_api.helpers.action_execution_metadata import (
    project_allowed_actions_payload,
    resolve_current_stage,
)


class OperationExecutionService:
    """Action Config policy — allowed actions and validation."""

    @staticmethod
    def get_allowed_actions(
        *,
        booking=None,
        shipment=None,
        movement=None,
        booking_item_type: str = '',
        exclude_log_id=None,
        include_action_id=None,
    ):
        return get_allowed_actions(
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            exclude_log_id=exclude_log_id,
            include_action_id=include_action_id,
        )

    @staticmethod
    def validate_operation_action_allowed(
        operation_action,
        *,
        booking=None,
        shipment=None,
        movement=None,
        booking_item_type: str = '',
        exclude_log_id=None,
        previous_action_id=None,
    ) -> str | None:
        return validate_operation_action_allowed(
            operation_action,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            exclude_log_id=exclude_log_id,
            previous_action_id=previous_action_id,
        )

    @staticmethod
    def action_options_payload(actions) -> list[dict[str, Any]]:
        return action_options_payload(actions)

    @staticmethod
    def allowed_actions_context_label(
        *,
        booking=None,
        shipment=None,
        booking_item_type: str = '',
    ) -> str:
        return allowed_actions_context_label(
            booking=booking,
            shipment=shipment,
            booking_item_type=booking_item_type,
        )

    @staticmethod
    def get_allowed_driver_actions(
        *,
        booking=None,
        shipment=None,
        movement=None,
        booking_item_type: str = '',
        exclude_log_id=None,
        include_action_id=None,
        request=None,
        job_type: str = '',
        job_id: str = '',
        job_no: str = '',
    ) -> dict[str, Any]:
        """
        Mobile allowed-actions payload — membership from ``get_allowed_actions`` only.
        """
        allowed_list = list(
            OperationExecutionService.get_allowed_actions(
                booking=booking,
                shipment=shipment,
                movement=movement,
                booking_item_type=booking_item_type,
                exclude_log_id=exclude_log_id,
                include_action_id=include_action_id,
            )
        )
        context_label = OperationExecutionService.allowed_actions_context_label(
            booking=booking,
            shipment=shipment,
            booking_item_type=booking_item_type,
        )
        if movement is not None and shipment is None:
            from iroad_tenants.operation_runtime.movement_execution_engine import (
                movement_allowed_actions_context_label,
            )

            context_label = movement_allowed_actions_context_label(movement)
        current_stage = resolve_current_stage(shipment=shipment, movement=movement)
        return project_allowed_actions_payload(
            allowed_list,
            request=request,
            current_stage=current_stage,
            context_label=context_label,
            job_type=job_type,
            job_id=job_id,
            job_no=job_no,
        )

    validate_driver_action_execution = validate_operation_action_allowed
