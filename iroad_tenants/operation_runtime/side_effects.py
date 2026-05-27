"""
Post-save operation action impacts (doc Ch.2–4).

Portal and mobile execution must call ``apply_execution_side_effects`` inside
the same DB transaction as action log creation.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
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
from tenant_workspace.models import TenantOperationActionLog, TenantTruckMovementLog


def _is_collect_payment_action(action) -> bool:
    return bool(
        action is not None
        and bool(getattr(action, 'auto_treasury_post', False))
        and str(getattr(action, 'action_scope', '') or '').strip().casefold() == 'job'
        and int(getattr(action, 'sequence_number', 0) or 0) == 9
    )


def _is_confirm_loaded_action(action) -> bool:
    return bool(
        getattr(action, 'auto_shipment_post', False)
        and operation_action_matches(action, 'confirm loaded', 'a4', 'action 4')
    )


def _is_depart_in_transit_action(action) -> bool:
    return operation_action_matches(
        action,
        'depart in transit',
        'depart',
        'a5',
        'action 5',
    )


def _is_unloading_completed_action(action) -> bool:
    return operation_action_matches(
        action,
        'unloading completed',
        'unloading',
        'a8',
        'action 8',
    )


def _assert_a3_fired_for_a4(action_log) -> None:
    if not _is_confirm_loaded_action(action_log.operation_action):
        return
    booking = action_log.booking
    if booking is None:
        raise ValidationError('Booking is required before Confirm Loaded can create a shipment.')
    qs = TenantOperationActionLog.objects.filter(booking_id=booking.pk).exclude(
        pk=action_log.pk,
    )
    booking_item_type = (
        getattr(action_log, '_birth_booking_item_type', None)
        or getattr(action_log, 'booking_item_type', '')
        or ''
    ).strip()
    if booking_item_type:
        qs = qs.filter(
            models.Q(shipment__isnull=True)
            | models.Q(shipment__booking_item_type__iexact=booking_item_type)
        )
    if not qs.filter(
        operation_action__action_code__iexact='A3',
    ).exists() and not qs.filter(
        operation_action__english_label__icontains='Start Loading',
    ).exists():
        raise ValidationError('Start Loading must be executed before Confirm Loaded.')


def _loaded_movement_for_shipment(shipment):
    if shipment is None:
        return None
    return (
        TenantTruckMovementLog.objects.filter(shipment_id=shipment.pk)
        .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
        .order_by('-created_at')
        .first()
    )


def _require_loaded_movement_for_action(action_log, shipment):
    movement = action_log.truck_movement or _loaded_movement_for_shipment(shipment)
    if movement is not None:
        if action_log.truck_movement_id != movement.pk:
            action_log.truck_movement = movement
            action_log.save(update_fields=['truck_movement', 'updated_at'])
        return movement
    action = action_log.operation_action
    if _is_depart_in_transit_action(action):
        raise ValidationError(
            'Movement record not found. Action 4 may not have completed correctly.'
        )
    if _is_unloading_completed_action(action):
        raise ValidationError(
            'Movement record not found. Action 4 may not have completed correctly.'
        )
    return None


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

    if shipment is None and _is_depart_in_transit_action(action):
        raise ValidationError(
            'Shipment not found. Confirm Loaded must be executed first.'
        )

    # Start Job (A1) execution date stamp — disabled until driver API is implemented.
    # if booking is not None and operation_action_matches(action, 'start job', 'a1', 'action 1'):
    #     if booking.execution_date is None:
    #         booking.execution_date = shipment_date
    #         booking.save(update_fields=['execution_date', 'updated_at'])

    if booking is not None and (action.booking_status_impact or '').strip():
        apply_booking_status_impact(booking, action.booking_status_impact)

    if booking is not None and shipment is None and action.auto_shipment_post:
        _assert_a3_fired_for_a4(action_log)
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
        if not _is_confirm_loaded_action(action):
            raise ValidationError(
                'Movement creation is only allowed during Confirm Loaded.'
            )
        truck_movement = birth_movement_for_shipment(
            shipment,
            movement_date=shipment_date,
            created_by_label=created_by_label,
        )
        action_log.truck_movement = truck_movement
        action_log.save(update_fields=['truck_movement', 'updated_at'])

    if (
        shipment is not None
        and truck_movement is None
        and (action.movement_status_impact or '').strip()
    ):
        truck_movement = _require_loaded_movement_for_action(action_log, shipment)

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

    if shipment is not None and (
        getattr(action, 'auto_treasury_post', False)
        or _is_collect_payment_action(action)
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

            if (
                movement_status == truck_movement.Status.COMPLETED
                and not _is_unloading_completed_action(action)
            ):
                completion_err = validate_movement_completion_stage(truck_movement)
                if completion_err:
                    from django.core.exceptions import ValidationError

                    raise ValidationError(completion_err)
            truck_movement.status = movement_status
            update_fields = ['status', 'updated_at']
            if movement_status == truck_movement.Status.IN_PROGRESS:
                truck_movement.start_time = timezone.now()
                update_fields.append('start_time')
            elif movement_status == truck_movement.Status.COMPLETED:
                truck_movement.end_time = timezone.now()
                update_fields.append('end_time')
            truck_movement.save(update_fields=update_fields)
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
