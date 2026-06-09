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
    apply_hard_copy_received_if_needed,
    apply_shipment_status_impact,
)
from iroad_tenants.operation_runtime.movement_ops import birth_movement_for_shipment
from iroad_tenants.operation_runtime.pod_action import (
    apply_pod_posting_from_action_log,
    birth_pod_from_action_log,
)
from tenant_workspace.models import (
    TenantOperationAction,
    TenantOperationActionLog,
    TenantShipment,
    TenantTruckMovementLog,
)


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
    if action is not None:
        category = (getattr(action, 'sequence_category', None) or '').strip()
        code = (getattr(action, 'action_code', None) or '').strip().upper()
        if category == 'empty_move' or code.startswith('EM'):
            return False
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


def _should_auto_mark_delivered_for_credit(action, shipment) -> bool:
    if shipment is None or not _is_unloading_completed_action(action):
        return False
    if (shipment.order_type or '').strip().upper() == 'COD':
        return False
    return (shipment.shipment_status or '').strip() in {
        shipment.ShipmentStatus.IN_TRANSIT,
        shipment.ShipmentStatus.AT_DELIVERY,
        shipment.ShipmentStatus.POD_SUBMITTED,
    }


def _pod_status_is_complete(shipment) -> bool:
    pod_status = (getattr(shipment, 'pod_status', None) or '').strip()
    return pod_status in {
        TenantShipment.PodStatus.COMPLIANT,
        TenantShipment.PodStatus.HARD_COPY_RECEIVED,
    }


def _mobile_log_evidence_for_shipment(shipment) -> dict[str, bool]:
    from mobile_api.pod_capture.policy.compliance_log_evidence import (
        log_evidence_flags,
    )

    logs = list(
        TenantOperationActionLog.objects.filter(shipment_id=shipment.pk)
        .select_related('operation_action')
        .order_by('-log_date', '-created_at')[:100],
    )
    return log_evidence_flags(logs)


def _mobile_pod_compliance_satisfied(shipment) -> bool:
    """Action Log + column — Hard POD needs A7H (hard_pod_log), not digital A7 alone."""
    if _pod_status_is_complete(shipment):
        return True
    evidence = _mobile_log_evidence_for_shipment(shipment)
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    if pod_type == TenantShipment.PodType.HARD.casefold():
        return bool(evidence.get('hard_pod_log'))
    return bool(evidence.get('pod_uploaded'))


def _sync_pod_status_from_mobile_logs(shipment) -> None:
    """Align pod_status column with mobile Action Log evidence before Delivered gates."""
    if shipment is None or _pod_status_is_complete(shipment):
        return
    evidence = _mobile_log_evidence_for_shipment(shipment)
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    if pod_type == TenantShipment.PodType.HARD.casefold():
        if evidence.get('hard_pod_log'):
            shipment.pod_status = TenantShipment.PodStatus.HARD_COPY_RECEIVED
            shipment.save(update_fields=['pod_status', 'updated_at'])
        return
    if evidence.get('pod_uploaded'):
        shipment.pod_status = TenantShipment.PodStatus.COMPLIANT
        shipment.save(update_fields=['pod_status', 'updated_at'])


def _should_auto_mark_delivered_for_cod(action, shipment) -> bool:
    """After A9 on COD: advance to Delivered when POD is complete and cash collected."""
    if shipment is None or not _is_collect_payment_action(action):
        return False
    if (shipment.order_type or '').strip().upper() != 'COD':
        return False
    if (
        getattr(shipment, 'collection_status', None)
        != TenantShipment.CollectionStatus.COLLECTED
    ):
        return False
    _sync_pod_status_from_mobile_logs(shipment)
    if not _mobile_pod_compliance_satisfied(shipment):
        return False
    current = (shipment.shipment_status or '').strip()
    return current in {
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
    }


def _ensure_auto_delivered_verify_log(
    shipment,
    *,
    action_log: TenantOperationActionLog,
    created_by_label: str = '',
    source_channel: str = 'auto_cod_verify',
    notes: str = 'Auto POD verified after COD collection',
) -> None:
    """
    Log-primary reconciler: append a Delivered-impact row so authoritative_status
    advances with the column (tenant Action Master ``A_POD_VERIFY`` when present).
    """
    from iroad_tenants.operation_runtime.action_master_catalog import (
        resolve_auto_cod_verify_action,
    )

    verify_action = resolve_auto_cod_verify_action()
    if verify_action is None:
        return

    shipment_pk = str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', ''))
    idempotency_key = f'auto-pod-verify-{shipment_pk}'
    log_no = f'LOG-POD-VERIFY-{shipment_pk[:24]}'

    log_row, _created = TenantOperationActionLog.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            'log_no': log_no,
            'log_sequence': 99,
            'log_date': timezone.now(),
            'operation_action': verify_action,
            'source': 'System',
            'source_channel': source_channel,
            'source_ref': source_channel,
            'created_by_label': created_by_label or 'system',
            'notes': notes,
            'booking': getattr(shipment, 'booking', None),
            'shipment': shipment,
            'truck': getattr(shipment, 'truck', None),
            'driver': getattr(action_log, 'driver', None) or getattr(shipment, 'driver', None),
            'truck_movement': getattr(action_log, 'truck_movement', None),
        },
    )
    if log_row.operation_action_id != verify_action.pk:
        log_row.operation_action = verify_action
        log_row.source_channel = source_channel
        log_row.save(
            update_fields=['operation_action', 'source_channel', 'updated_at'],
        )


def _apply_auto_delivered_for_cod(
    shipment,
    *,
    action_log: TenantOperationActionLog,
    created_by_label: str = '',
) -> None:
    if not _should_auto_mark_delivered_for_cod(action_log.operation_action, shipment):
        return
    _ensure_auto_delivered_verify_log(
        shipment,
        action_log=action_log,
        created_by_label=created_by_label,
        source_channel='auto_cod_verify',
        notes='Auto POD verified after COD collection',
    )
    shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
    shipment.save(update_fields=['shipment_status', 'updated_at'])


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

    if action.auto_shipment_post and action.auto_movement_post:
        if shipment is not None and truck_movement is None:
            raise ValidationError(
                'Atomic birth failed: Shipment was created '
                'but Movement was not. '
                'Both must succeed or neither should persist. '
                'Transaction will roll back.'
            )

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
    elif _should_auto_mark_delivered_for_credit(action, shipment):
        _ensure_auto_delivered_verify_log(
            shipment,
            action_log=action_log,
            created_by_label=created_by_label,
            source_channel='auto_pod_verify',
            notes='Auto POD verified after credit POD completion',
        )
        shipment.shipment_status = shipment.ShipmentStatus.DELIVERED
        shipment.save(update_fields=['shipment_status', 'updated_at'])

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
        shipment.refresh_from_db(
            fields=[
                'collection_status',
                'shipment_status',
                'pod_status',
                'order_type',
                'updated_at',
            ],
        )
        _apply_auto_delivered_for_cod(
            shipment,
            action_log=action_log,
            created_by_label=created_by_label,
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
        apply_hard_copy_received_if_needed(shipment=shipment, action=action)
