"""
Post-save operation action impacts (doc Ch.2–4).

Portal and mobile execution must call ``apply_execution_side_effects`` inside
the same DB transaction as action log creation.
"""

from __future__ import annotations

from django.utils import timezone

from iroad_tenants.operation_runtime.booking_impact import apply_booking_status_impact
from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_movement_status_impact,
)
from iroad_tenants.operation_runtime.latest_state import (
    apply_hard_copy_pod_type_if_needed,
    apply_shipment_status_impact,
)
from iroad_tenants.operation_runtime.movement_ops import birth_movement_for_shipment
from iroad_tenants.operation_runtime.pod_action import (
    apply_pod_posting_from_action_log,
    birth_pod_from_action_log,
)


def apply_execution_side_effects(action_log, *, created_by_label='') -> None:
    """
    Apply Action Master impacts after log save (doc Ch.2–4).
    Atomic shipment + movement birth when auto_post flags or Confirm Loaded action.
    """
    action = action_log.operation_action
    if action is None:
        return

    booking = action_log.booking
    shipment = action_log.shipment
    truck_movement = action_log.truck_movement
    log_date = action_log.log_date
    shipment_date = log_date.date() if log_date else timezone.localdate()

    # Start Job (A1) execution date stamp — disabled until driver API is implemented.
    # if booking is not None and operation_action_matches(action, 'start job', 'a1', 'action 1'):
    #     if booking.execution_date is None:
    #         booking.execution_date = shipment_date
    #         booking.save(update_fields=['execution_date', 'updated_at'])

    if booking is not None and (action.booking_status_impact or '').strip():
        apply_booking_status_impact(booking, action.booking_status_impact)

    if booking is not None and shipment is None and action.auto_shipment_post:
        from iroad_tenants.views import (
            _tenant_shipment_birth_from_booking_line,
            _tenant_shipment_booking_line_rows,
            _tenant_shipment_has_active_duplicate,
            _tenant_shipment_match_booking_line,
        )

        booking_item_type_hint = (
            getattr(action_log, '_birth_booking_item_type', None) or ''
        ).strip()
        target_line = _tenant_shipment_match_booking_line(
            booking,
            booking_item_type=booking_item_type_hint,
        )
        if target_line is None:
            for line in _tenant_shipment_booking_line_rows(booking):
                if not _tenant_shipment_has_active_duplicate(
                    booking,
                    line['booking_item_type'],
                ):
                    target_line = line
                    break
        if target_line is None:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                'Auto Shipment Post requires a confirmed booking line without an active shipment.'
            )
        shipment = _tenant_shipment_birth_from_booking_line(
            booking,
            target_line,
            shipment_date=shipment_date,
            created_by_label=created_by_label,
        )
        action_log.shipment = shipment
        action_log.truck = shipment.truck
        action_log.driver = shipment.driver
        action_log.save(update_fields=['shipment', 'truck', 'driver', 'updated_at'])

    if shipment is not None and truck_movement is None and action.auto_movement_post:
        truck_movement = birth_movement_for_shipment(
            shipment,
            movement_date=shipment_date,
            created_by_label=created_by_label,
        )
        action_log.truck_movement = truck_movement
        action_log.save(update_fields=['truck_movement', 'updated_at'])

    if shipment is not None and action.auto_pod_post:
        pod_document = birth_pod_from_action_log(
            action_log,
            created_by_label=created_by_label,
        )
        apply_pod_posting_from_action_log(
            action_log=action_log,
            pod_document=pod_document,
            shipment=shipment,
            created_by_label=created_by_label,
        )

    if shipment is not None and (action.shipment_status_impact or '').strip():
        apply_shipment_status_impact(
            shipment=shipment,
            action=action,
            created_by_label=created_by_label,
        )

    if shipment is not None and operation_action_matches(
        action,
        'collect payment',
        'a9',
        'action 9',
    ):
        from iroad_tenants.services.cod_execution_service import CODExecutionService

        CODExecutionService.apply_collect_payment_side_effect(
            shipment=shipment,
            action_log=action_log,
            amount=getattr(action_log, '_mobile_cod_amount', None),
        )

    if truck_movement is not None and (action.movement_status_impact or '').strip():
        movement_status = resolve_movement_status_impact(action.movement_status_impact)
        if movement_status:
            from iroad_tenants.operation_runtime.movement_action_validator import (
                validate_movement_completion_stage,
            )
            from iroad_tenants.operation_runtime.movement_stage_derivation import (
                derive_movement_execution_stage,
                sync_movement_timestamps_from_stage,
            )

            if movement_status == truck_movement.Status.COMPLETED:
                completion_err = validate_movement_completion_stage(truck_movement)
                if completion_err:
                    from django.core.exceptions import ValidationError

                    raise ValidationError(completion_err)
            truck_movement.status = movement_status
            truck_movement.save(update_fields=['status', 'updated_at'])
            sync_movement_timestamps_from_stage(
                truck_movement,
                stage=derive_movement_execution_stage(truck_movement),
            )

    if truck_movement is not None and shipment is None:
        from iroad_tenants.operation_runtime.movement_state_machine import (
            is_movement_start_action,
        )
        from iroad_tenants.operation_runtime.movement_stage_derivation import (
            derive_movement_execution_stage,
            sync_movement_timestamps_from_stage,
        )

        if (
            is_movement_start_action(action)
            and truck_movement.status == truck_movement.Status.SCHEDULED
        ):
            truck_movement.status = truck_movement.Status.IN_PROGRESS
            truck_movement.save(update_fields=['status', 'updated_at'])
        sync_movement_timestamps_from_stage(
            truck_movement,
            stage=derive_movement_execution_stage(truck_movement),
        )

    if shipment is not None:
        apply_hard_copy_pod_type_if_needed(shipment=shipment, action=action)
