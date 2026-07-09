"""
Post-save operation action impacts (doc Ch.2–4).

Portal and mobile execution must call ``apply_execution_side_effects`` inside
the same DB transaction as action log creation.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from iroad_tenants.operation_field_catalog import (
    normalize_operation_pod_status,
    operation_pod_status_is_complete,
)
from iroad_tenants.operation_runtime.booking_impact import apply_booking_status_impact
from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_movement_status_impact,
    resolve_shipment_status_impact,
)
from iroad_tenants.operation_runtime.latest_state import (
    after_shipment_status_side_effects,
    apply_hard_copy_pod_type_if_needed,
    apply_hard_copy_received_if_needed,
    apply_shipment_status_impact,
    resolve_effective_shipment_status_for_action,
)
from iroad_tenants.operation_runtime.movement_action_validator import (
    is_empty_move_catalog_action,
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
    if action is not None and is_empty_move_catalog_action(action):
        return False
    return operation_action_matches(
        action,
        'depart in transit',
        'depart',
        'a5',
        'action 5',
    )


def _is_unloading_completed_action(action) -> bool:
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        is_unloading_completed_action,
    )

    return is_unloading_completed_action(action)


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
    return operation_pod_status_is_complete(pod_status)


def _mobile_log_evidence_for_shipment(shipment) -> dict[str, bool]:
    from mobile_api.pod_capture.policy.compliance_log_evidence import (
        log_evidence_flags,
    )

    logs = list(
        TenantOperationActionLog.objects.filter(shipment_id=shipment.pk)
        .select_related('operation_action')
        .order_by('-log_date', '-created_at')[:100],
    )
    evidence = log_evidence_flags(logs)
    try:
        from mobile_api.dashboard.selectors.pod_cod_policy import (
            enrich_log_evidence_hard_pod,
            shipment_requires_hard_copy,
        )

        if shipment_requires_hard_copy(shipment):
            evidence = enrich_log_evidence_hard_pod(
                evidence,
                shipment,
                logs=logs,
            )
    except Exception:
        pass
    return evidence


def _mobile_pod_compliance_satisfied(shipment) -> bool:
    """Action Log + column — Hard POD needs custody complete, not column alone."""
    if shipment is None:
        return False
    from mobile_api.dashboard.selectors.pod_cod_policy import (
        is_hard_pod_custody_complete,
        shipment_requires_hard_copy,
    )

    evidence = _mobile_log_evidence_for_shipment(shipment)
    try:
        from django.db import connection

        schema = (getattr(connection, 'schema_name', None) or '').strip()
    except Exception:
        schema = ''
    evidence = dict(evidence)
    try:
        from mobile_api.dashboard.selectors import pod_cod_policy as policy

        logs = list(
            TenantOperationActionLog.objects.filter(shipment_id=shipment.pk)
            .select_related('operation_action')
            .order_by('-log_date', '-created_at')[:100],
        )
        evidence = policy.enrich_log_evidence_hard_pod(
            evidence,
            shipment,
            tenant_schema=schema,
            driver=getattr(shipment, 'driver', None),
            logs=logs,
        )
    except Exception:
        pass
    if shipment_requires_hard_copy(shipment):
        if not is_hard_pod_custody_complete(
            shipment,
            log_evidence=evidence,
            tenant_schema=schema,
            driver=getattr(shipment, 'driver', None),
        ):
            return False
        return bool(evidence.get('pod_uploaded')) or _pod_status_is_complete(shipment)
    if _pod_status_is_complete(shipment):
        return True
    return bool(evidence.get('pod_uploaded'))


def _sync_pod_status_from_mobile_logs(shipment) -> None:
    """Align pod_status column with mobile Action Log evidence before Delivered gates."""
    if shipment is None or _pod_status_is_complete(shipment):
        return
    evidence = _mobile_log_evidence_for_shipment(shipment)
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    if pod_type == TenantShipment.PodType.HARD.casefold():
        if evidence.get('hard_pod_log'):
            shipment.pod_status = TenantShipment.PodStatus.COMPLETED
            shipment.save(update_fields=['pod_status', 'updated_at'])
        return
    if evidence.get('pod_uploaded') or evidence.get('delivered_log'):
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            _shipment_pod_upload_substantively_complete,
        )

        if not _shipment_pod_upload_substantively_complete(shipment):
            return
        shipment.pod_status = TenantShipment.PodStatus.COMPLETED
        shipment.save(update_fields=['pod_status', 'updated_at'])


def derive_pod_status_from_shipment_rows(statuses: list[str]) -> str:
    """Aggregate shipment pod_status values for booking-level display."""
    normalized = [
        normalize_operation_pod_status(status, default=TenantShipment.PodStatus.NOT_COMPLETED)
        for status in statuses
        if (status or '').strip()
    ]
    if not normalized:
        return TenantShipment.PodStatus.NOT_COMPLETED
    if any(status == TenantShipment.PodStatus.NOT_COMPLETED for status in normalized):
        return TenantShipment.PodStatus.NOT_COMPLETED
    if all(status == TenantShipment.PodStatus.COMPLETED for status in normalized):
        return TenantShipment.PodStatus.COMPLETED
    return TenantShipment.PodStatus.NOT_COMPLETED


def sync_booking_pod_status_from_shipments(booking) -> None:
    """Persist booking.pod_status from linked shipment POD columns after job completion."""
    if booking is None:
        return
    from tenant_workspace.models import TenantBooking

    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    if not booking_id:
        return
    statuses = list(
        TenantShipment.objects.filter(booking_id=booking_id)
        .exclude(shipment_status=TenantShipment.ShipmentStatus.CANCELLED)
        .values_list('pod_status', flat=True),
    )
    if not statuses:
        return
    new_status = derive_pod_status_from_shipment_rows(statuses)
    if (getattr(booking, 'pod_status', None) or '').strip() == new_status:
        return
    TenantBooking.objects.filter(pk=booking_id).update(
        pod_status=new_status,
        updated_at=timezone.now(),
    )
    booking.pod_status = new_status


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
    Log-primary reconciler: append a backend-only Delivered milestone row.

    No Action Master row is required — ``operation_action`` stays NULL and
    timeline consumers key off ``source_channel``.
    """
    from iroad_tenants.operation_runtime.action_master_catalog import (
        AUTO_COD_VERIFY_IDEMPOTENCY_PREFIX,
        AUTO_COD_VERIFY_LOG_NO_PREFIX,
    )

    shipment_pk = str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', ''))
    idempotency_key = f'{AUTO_COD_VERIFY_IDEMPOTENCY_PREFIX}{shipment_pk}'
    log_no = f'{AUTO_COD_VERIFY_LOG_NO_PREFIX}{shipment_pk[:24]}'

    log_row, _created = TenantOperationActionLog.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            'log_no': log_no,
            'log_sequence': 99,
            'log_date': timezone.now(),
            'operation_action': None,
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
    patch_fields: list[str] = []
    if log_row.source_channel != source_channel:
        log_row.source_channel = source_channel
        log_row.source_ref = source_channel
        patch_fields.extend(['source_channel', 'source_ref'])
    if log_row.operation_action_id is not None:
        log_row.operation_action = None
        patch_fields.append('operation_action')
    if patch_fields:
        patch_fields.append('updated_at')
        log_row.save(update_fields=patch_fields)


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


def maybe_advance_delivered_when_job_close_ready(
    shipment,
    *,
    created_by_label: str = 'system',
) -> bool:
    """
    When POD/COD gates pass but the column is still POD Submitted, advance to
    Delivered so A10 (Job Closed) appears on mobile Job Detail refresh.
    """
    if shipment is None:
        return False
    current = (shipment.shipment_status or '').strip()
    if current != TenantShipment.ShipmentStatus.POD_SUBMITTED:
        return False
    try:
        from mobile_api.dashboard.selectors.pod_cod_policy import derive_hard_pod_pending

        if derive_hard_pod_pending(shipment):
            return False
    except Exception:
        pass
    if not _shipment_job_close_gates_satisfied_for_advance(shipment):
        return False
    anchor_log = (
        TenantOperationActionLog.objects.filter(shipment_id=shipment.pk)
        .exclude(operation_action__isnull=True)
        .order_by('-log_date', '-created_at')
        .first()
    )
    if anchor_log is None:
        return False
    _ensure_auto_delivered_verify_log(
        shipment,
        action_log=anchor_log,
        created_by_label=created_by_label,
        source_channel='mobile_job_close_ready',
        notes='Auto POD verified when job-close gates satisfied',
    )
    shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    return True


def maybe_advance_shipment_after_hard_pod_custody(
    shipment,
    *,
    action_log: TenantOperationActionLog | None = None,
    created_by_label: str = 'system',
) -> bool:
    """
    After hard-copy custody promotion: when digital + hard-copy are both complete,
    advance ``shipment_status`` to POD Submitted and ``pod_status`` to Completed.
    """
    _ = action_log
    _ = created_by_label
    if shipment is None:
        return False
    current = (shipment.shipment_status or '').strip()
    if current in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }:
        return False
    try:
        from mobile_api.dashboard.selectors.pod_cod_policy import derive_hard_pod_pending

        if derive_hard_pod_pending(shipment):
            return False
    except Exception:
        return False

    _sync_pod_status_from_mobile_logs(shipment)
    if hasattr(shipment, 'refresh_from_db'):
        shipment.refresh_from_db(
            fields=['pod_status', 'shipment_status', 'order_type', 'updated_at'],
        )

    if not _mobile_pod_compliance_satisfied(shipment):
        return False

    pod_type = (getattr(shipment, 'pod_type', None) or '').strip()
    if pod_type == TenantShipment.PodType.HARD:
        if (getattr(shipment, 'pod_status', None) or '').strip() != (
            TenantShipment.PodStatus.COMPLETED
        ):
            shipment.pod_status = TenantShipment.PodStatus.COMPLETED
            shipment.save(update_fields=['pod_status', 'updated_at'])

    if current != TenantShipment.ShipmentStatus.POD_SUBMITTED:
        shipment.shipment_status = TenantShipment.ShipmentStatus.POD_SUBMITTED
        shipment.save(update_fields=['shipment_status', 'updated_at'])

    from iroad_tenants.operation_runtime.latest_state import after_shipment_status_side_effects

    after_shipment_status_side_effects(shipment)
    booking = getattr(shipment, 'booking', None)
    if booking is None and getattr(shipment, 'booking_id', None):
        from tenant_workspace.models import TenantBooking

        booking = TenantBooking.objects.filter(pk=shipment.booking_id).first()
    sync_booking_pod_status_from_shipments(booking)
    return True


def _shipment_job_close_gates_satisfied_for_advance(shipment) -> bool:
    if not _mobile_pod_compliance_satisfied(shipment):
        return False
    if (shipment.order_type or '').strip().upper() == 'COD':
        if (
            getattr(shipment, 'collection_status', None)
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return False
    return True


def _should_auto_close_shipment(shipment) -> bool:
    """Delivered leg with POD (+ COD when applicable) may auto-close (A10)."""
    if shipment is None:
        return False
    if (shipment.shipment_status or '').strip() != TenantShipment.ShipmentStatus.DELIVERED:
        return False
    _sync_pod_status_from_mobile_logs(shipment)
    if hasattr(shipment, 'refresh_from_db'):
        shipment.refresh_from_db(
            fields=[
                'pod_status',
                'collection_status',
                'order_type',
                'pod_type',
                'shipment_status',
                'updated_at',
            ],
        )
    if not _mobile_pod_compliance_satisfied(shipment):
        return False
    if (shipment.order_type or '').strip().upper() == 'COD':
        if (
            getattr(shipment, 'collection_status', None)
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return False
    return True


def _ensure_auto_close_job_log(
    shipment,
    *,
    action_log: TenantOperationActionLog | None = None,
    created_by_label: str = '',
    source_channel: str = 'auto_job_close',
    notes: str = 'Auto job close after delivery completion',
) -> None:
    from iroad_tenants.operation_runtime.action_master_catalog import (
        resolve_auto_close_job_action,
    )
    from iroad_tenants.views import (
        _next_auto_number_for_form,
        OPERATION_ACTION_LOG_AUTO_FORM_CODE,
        OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
        OPERATION_ACTION_LOG_REF_PREFIX,
    )

    close_action = resolve_auto_close_job_action()
    if close_action is None:
        return

    shipment_pk = str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', ''))
    idempotency_key = f'auto-job-close-{shipment_pk}'

    existing = TenantOperationActionLog.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return

    log_no = ''
    log_sequence = 0
    for _ in range(10):
        log_no, log_sequence = _next_auto_number_for_form(
            form_code=OPERATION_ACTION_LOG_AUTO_FORM_CODE,
            form_label=OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
            prefix=OPERATION_ACTION_LOG_REF_PREFIX,
        )
        if not TenantOperationActionLog.objects.filter(log_no=log_no).exists():
            break

    if not log_no or TenantOperationActionLog.objects.filter(log_no=log_no).exists():
        log_no = f'LOG-JOB-CLOSE-{shipment_pk[:24]}'
        log_sequence = 100

    driver = None
    if action_log is not None:
        driver = getattr(action_log, 'driver', None)
    if driver is None:
        driver = getattr(shipment, 'driver', None)

    log_row, _created = TenantOperationActionLog.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            'log_no': log_no,
            'log_sequence': log_sequence,
            'log_date': timezone.now(),
            'operation_action': close_action,
            'source': 'System',
            'source_channel': source_channel,
            'source_ref': source_channel,
            'created_by_label': created_by_label or 'system',
            'notes': notes,
            'booking': getattr(shipment, 'booking', None),
            'shipment': shipment,
            'truck': getattr(shipment, 'truck', None),
            'driver': driver,
        },
    )
    if log_row.operation_action_id != close_action.pk:
        log_row.operation_action = close_action
        log_row.source_channel = source_channel
        log_row.save(
            update_fields=['operation_action', 'source_channel', 'updated_at'],
        )


def _apply_auto_close_when_ready(
    shipment,
    *,
    action_log: TenantOperationActionLog | None = None,
    created_by_label: str = '',
) -> bool:
    """
    Advance Delivered → Closed when POD/COD gates are satisfied (A10 equivalent).

    Returns True when the shipment column was closed.
    """
    if not _should_auto_close_shipment(shipment):
        return False
    _ensure_auto_close_job_log(
        shipment,
        action_log=action_log,
        created_by_label=created_by_label,
    )
    shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    booking = getattr(shipment, 'booking', None)
    if booking is not None:
        from iroad_tenants.operation_runtime.action_master_catalog import (
            resolve_auto_close_job_action,
        )

        close_action = resolve_auto_close_job_action()
        if close_action is not None:
            apply_booking_status_impact(
                booking,
                getattr(close_action, 'booking_status_impact', '') or '',
            )
    from iroad_tenants.operation_runtime.latest_state import (
        after_shipment_status_side_effects,
    )

    after_shipment_status_side_effects(shipment)
    return True


def maybe_auto_close_delivered_shipment(shipment, *, created_by_label: str = '') -> bool:
    """
    Manual repair helper only — not invoked from mobile execute or payment flows.

    Drivers must tap Job Closed (A10) on the mobile app.
    """
    return _apply_auto_close_when_ready(
        shipment,
        action_log=None,
        created_by_label=created_by_label,
    )


def _preshipment_logs_before_confirm_loaded(action_log) -> Any:
    """Logs that count toward A1–A3 prerequisites for Confirm Loaded (A4)."""
    from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
        booking_preshipment_logs_queryset,
        is_backload_preshipment_cycle,
    )

    booking = action_log.booking
    if booking is None:
        return TenantOperationActionLog.objects.none()

    booking_item_type = (
        getattr(action_log, '_birth_booking_item_type', None)
        or getattr(action_log, 'booking_item_type', '')
        or ''
    ).strip()

    if is_backload_preshipment_cycle(booking, booking_item_type):
        return booking_preshipment_logs_queryset(
            booking,
            booking_item_type=booking_item_type,
            exclude_log_id=action_log.pk,
        )

    qs = TenantOperationActionLog.objects.filter(booking_id=booking.pk).exclude(
        pk=action_log.pk,
    )
    if booking_item_type:
        qs = qs.filter(
            models.Q(shipment__isnull=True)
            | models.Q(shipment__booking_item_type__iexact=booking_item_type)
        )
    return qs


def _assert_a3_fired_for_a4(action_log) -> None:
    if not _is_confirm_loaded_action(action_log.operation_action):
        return
    booking = action_log.booking
    if booking is None:
        raise ValidationError('Booking is required before Confirm Loaded can create a shipment.')
    qs = _preshipment_logs_before_confirm_loaded(action_log)

    if not qs.filter(
        models.Q(operation_action__action_code__iexact='A1')
        | models.Q(operation_action__english_label__icontains='Start Job'),
    ).exists():
        raise ValidationError('Start Job must be executed before Confirm Loaded.')

    if not qs.filter(
        models.Q(operation_action__action_code__iexact='A2')
        | models.Q(operation_action__english_label__icontains='Pickup Arrival'),
    ).exists():
        raise ValidationError('Pickup Arrival must be executed before Confirm Loaded.')

    if not qs.filter(
        models.Q(operation_action__action_code__iexact='A3')
        | models.Q(operation_action__english_label__icontains='Start Loading'),
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


def _peer_ready_for_round_trip_cascade_close(shipment) -> bool:
    """
    Sibling leg may be closed when the driver closes the final round-trip leg.

    Unlike driver-initiated A10 on outbound, cascade close ignores
    ``round_trip_defers_job_close`` — outbound stays Delivered until backload
    job close runs.
    """
    if shipment is None:
        return False
    current = (shipment.shipment_status or '').strip()
    if current in {
        TenantShipment.ShipmentStatus.CANCELLED,
        TenantShipment.ShipmentStatus.CLOSED,
    }:
        return False
    if current not in {
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }:
        return False
    if not _mobile_pod_compliance_satisfied(shipment):
        return False
    if (shipment.order_type or '').strip().upper() == 'COD':
        if (
            getattr(shipment, 'collection_status', None)
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return False
    return True


def close_round_trip_peer_shipments_on_job_close(
    shipment,
    *,
    action,
    action_log: TenantOperationActionLog | None = None,
    created_by_label: str = '',
) -> int:
    """
    When the driver closes the final round-trip leg, close every sibling leg
    that already finished delivery (POD + COD when applicable).
    """
    from mobile_api.dashboard.selectors.booking_selection_policy import (
        normalized_trip_type,
    )

    if shipment is None or action is None:
        return 0
    impact = resolve_effective_shipment_status_for_action(
        action=action,
        shipment=shipment,
    )
    if impact != TenantShipment.ShipmentStatus.CLOSED:
        return 0

    booking = getattr(shipment, 'booking', None) or getattr(action_log, 'booking', None)
    if booking is None and getattr(shipment, 'booking_id', None):
        from tenant_workspace.models import TenantBooking

        booking = TenantBooking.objects.filter(pk=shipment.booking_id).first()
    if booking is None:
        return 0
    if normalized_trip_type(booking).casefold() != 'round':
        return 0

    anchor_code = str(
        getattr(shipment, 'shipment_no', None)
        or getattr(shipment, 'shipment_code', None)
        or getattr(shipment, 'pk', '')
    )
    closed_count = 0
    peers = (
        TenantShipment.objects.filter(booking_id=booking.pk)
        .exclude(pk=shipment.pk)
        .exclude(shipment_status=TenantShipment.ShipmentStatus.CANCELLED)
    )
    for peer in peers:
        if not _peer_ready_for_round_trip_cascade_close(peer):
            continue
        _ensure_auto_close_job_log(
            peer,
            action_log=action_log,
            created_by_label=created_by_label,
            source_channel='round_trip_cascade_job_close',
            notes=f'Round-trip cascade job close from leg {anchor_code}',
        )
        peer.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        peer.save(update_fields=['shipment_status', 'updated_at'])
        after_shipment_status_side_effects(peer)
        closed_count += 1

    if closed_count:
        apply_booking_status_impact(
            booking,
            getattr(action, 'booking_status_impact', '') or '',
        )
    return closed_count


def apply_execution_side_effects(action_log, *, created_by_label='') -> None:
    """
    Apply Action Master impacts after log save (doc Ch.2–4).
    Atomic shipment + movement birth when auto_post flags or Confirm Loaded action.
    """
    action = action_log.operation_action
    if action is None:
        return

    from iroad_tenants.operation_runtime.workflow_action_policy import (
        action_is_job_close,
    )

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
        )
        from iroad_tenants.operation_runtime.auto_shipment_line import (
            resolve_auto_shipment_target_line,
        )

        booking_item_type_hint = (
            getattr(action_log, '_birth_booking_item_type', None) or ''
        ).strip()

        target_line = resolve_auto_shipment_target_line(
            booking,
            booking_item_type_hint=booking_item_type_hint,
        )
        if target_line is None:
            from iroad_tenants.operation_runtime.auto_shipment_line import (
                format_auto_shipment_birth_error,
            )

            raise ValidationError(
                format_auto_shipment_birth_error(booking, booking_item_type_hint)
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

    hard_first_pod_execute = False
    run_hard_copy_promotion = False
    if shipment is not None:
        from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists
        from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod
        from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
            is_pod_upload_action,
        )

        custody_linked = bool(
            str(getattr(action_log, '_hard_pod_custody_submission_id', None) or '').strip()
            or str(getattr(action_log, '_hard_pod_client_submission_id', None) or '').strip()
        )
        run_hard_copy_promotion = bool(getattr(action, 'hard_copy_collection', False))
        if not run_hard_copy_promotion and operation_shipment_uses_hard_copy_pod(shipment):
            if is_pod_upload_action(action) and (
                custody_linked or _pending_hard_pod_custody_exists(shipment)
            ):
                run_hard_copy_promotion = True

    if shipment is not None and run_hard_copy_promotion:
        from iroad_tenants.operation_runtime.hard_pod_promotion import (
            promote_pending_hard_pod_custody_for_action_log,
        )
        from iroad_tenants.operation_runtime.latest_state import (
            apply_hard_copy_pod_type_if_needed,
            apply_hard_copy_received_if_needed,
        )

        had_pending_custody = _pending_hard_pod_custody_exists(shipment)
        apply_hard_copy_pod_type_if_needed(shipment=shipment, action=action)
        promoted = promote_pending_hard_pod_custody_for_action_log(
            action_log=action_log,
            shipment=shipment,
            action=action,
            created_by_label=created_by_label,
        )
        hard_first_pod_execute = bool(had_pending_custody and promoted)
        if promoted:
            shipment.refresh_from_db()
        apply_hard_copy_received_if_needed(shipment=shipment, action=action)
        shipment.refresh_from_db()
        if promoted:
            maybe_advance_shipment_after_hard_pod_custody(
                shipment,
                action_log=action_log,
                created_by_label=created_by_label,
            )
            shipment.refresh_from_db()

    if shipment is not None and action.auto_pod_post and not hard_first_pod_execute:
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

    if shipment is not None and (
        (action.shipment_status_impact or '').strip()
        or action_is_job_close(action)
    ):
        from iroad_tenants.operation_runtime.latest_state import (
            resolve_effective_shipment_status_for_action,
        )

        impact_status = resolve_effective_shipment_status_for_action(
            action=action,
            shipment=shipment,
        )
        defer_delivered_for_hard_pod = False
        if impact_status == TenantShipment.ShipmentStatus.DELIVERED:
            if hard_first_pod_execute and getattr(action, 'auto_pod_post', False):
                defer_delivered_for_hard_pod = True
            elif (
                getattr(action, 'hard_copy_collection', False)
                and getattr(action, 'auto_pod_post', False)
                and (getattr(shipment, 'pod_type', None) or '').strip().casefold()
                == TenantShipment.PodType.HARD.casefold()
            ):
                evidence = _mobile_log_evidence_for_shipment(shipment)
                if not evidence.get('hard_pod_log'):
                    defer_delivered_for_hard_pod = True
        if not defer_delivered_for_hard_pod:
            apply_shipment_status_impact(
                shipment=shipment,
                action=action,
                created_by_label=created_by_label,
            )
            if impact_status == TenantShipment.ShipmentStatus.CLOSED:
                close_round_trip_peer_shipments_on_job_close(
                    shipment,
                    action=action,
                    action_log=action_log,
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
            is_movement_arrived_action,
            is_movement_in_transit_action,
            is_movement_start_action,
        )
        from iroad_tenants.operation_runtime.movement_stage_derivation import (
            derive_movement_execution_stage,
            sync_movement_timestamps_from_stage,
        )

        if (
            truck_movement.status == truck_movement.Status.SCHEDULED
            and (
                is_movement_start_action(action)
                or is_movement_in_transit_action(action)
                or is_movement_arrived_action(action)
            )
        ):
            truck_movement.status = truck_movement.Status.IN_PROGRESS
            truck_movement.save(update_fields=['status', 'updated_at'])
        sync_movement_timestamps_from_stage(
            truck_movement,
            stage=derive_movement_execution_stage(truck_movement),
        )
        from iroad_tenants.operation_runtime.movement_ops import (
            sync_movement_route_evidence_from_action_log,
        )

        sync_movement_route_evidence_from_action_log(action_log)

    # Job close (A10) is driver-initiated only — never auto-close after payment/POD.
