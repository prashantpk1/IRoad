"""Shipment cancel (PCS §4.2) — dynamic Operation Action log, no hard delete."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from iroad_tenants.operation_runtime.action_master_catalog import (
    WITHOUT_SCOPE_CANCEL_SHIPMENT_LABEL,
    cancel_action_configuration_error,
    resolve_cancel_shipment_action,
)
from iroad_tenants.operation_runtime.impacts import resolve_shipment_status_impact
from tenant_workspace.models import TenantShipment

DB_STATUS_CANCELLED = TenantShipment.ShipmentStatus.CANCELLED


def resolve_r1_cancel_action():
    return resolve_cancel_shipment_action()


def append_shipment_r1_cancel_action_log(
    *,
    shipment,
    operation_action=None,
    created_by_label: str = '',
    tenant_user=None,
    notes: str = '',
):
    """Append cancel-shipment entry to the Action Log (PCS §4.2.2)."""
    from iroad_tenants.views import (
        OPERATION_ACTION_LOG_AUTO_FORM_CODE,
        OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
        OPERATION_ACTION_LOG_REF_PREFIX,
        _next_auto_number_for_form,
    )
    from tenant_workspace.models import TenantOperationActionLog

    action = operation_action or resolve_cancel_shipment_action()
    if action is None:
        return None

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
    if TenantOperationActionLog.objects.filter(log_no=log_no).exists():
        return None

    action_code = (getattr(action, 'action_code', '') or '').strip()
    action_label = (getattr(action, 'english_label', '') or '').strip()
    action_ref = ' · '.join(part for part in (action_code, action_label) if part)
    note_text = (notes or '').strip() or (
        f'Shipment cancelled by admin ({action_ref}).' if action_ref
        else 'Shipment cancelled by admin.'
    )
    return TenantOperationActionLog.objects.create(
        log_no=log_no,
        log_sequence=log_sequence,
        log_date=timezone.now(),
        operation_action=action,
        source='Admin Reversal',
        source_channel='admin_manual',
        notes=note_text,
        booking=shipment.booking if shipment.booking_id else None,
        shipment=shipment,
        truck=shipment.truck if shipment.truck_id else None,
        driver=shipment.driver if shipment.driver_id else None,
        created_by=tenant_user,
        created_by_label=(created_by_label or '')[:200],
    )


def shipment_cancel_guard_errors(shipment) -> list[str]:
    """Return validation errors blocking cancel."""
    if shipment is None:
        return ['Shipment not found.']
    if (shipment.shipment_status or '').strip() == DB_STATUS_CANCELLED:
        return ['Shipment is already cancelled.']
    return []


def apply_shipment_cancel(
    shipment,
    *,
    created_by_label: str = '',
    tenant_user=None,
    notes: str = '',
):
    """
    Cancel shipment at any stage (PCS §4.2.1).
    Returns (success, errors).
    """
    errors = shipment_cancel_guard_errors(shipment)
    if errors:
        return False, errors

    operation_action = resolve_cancel_shipment_action()
    if operation_action is None:
        return False, [cancel_action_configuration_error(WITHOUT_SCOPE_CANCEL_SHIPMENT_LABEL)]

    cancelled_status = (
        resolve_shipment_status_impact(
            getattr(operation_action, 'shipment_status_impact', '')
        )
        or DB_STATUS_CANCELLED
    )

    with transaction.atomic():
        previous_status = shipment.shipment_status
        shipment._original_shipment_status = previous_status
        shipment.shipment_status = cancelled_status
        shipment.sync_collection_status_for_lifecycle()
        shipment.save()

        action_log = append_shipment_r1_cancel_action_log(
            shipment=shipment,
            operation_action=operation_action,
            created_by_label=created_by_label,
            tenant_user=tenant_user,
            notes=notes,
        )
        if action_log is None:
            raise RuntimeError(
                'Failed to record cancel action log for shipment '
                f'{getattr(shipment, "shipment_no", "")}.'
            )

    booking_id = getattr(shipment, 'booking_id', None)
    if booking_id:
        booking = getattr(shipment, 'booking', None)
        if booking is None:
            from tenant_workspace.models import TenantBooking

            booking = TenantBooking.objects.filter(pk=booking_id).first()
        if booking is not None:
            from iroad_tenants.booking_status import sync_booking_status_after_item_change

            sync_booking_status_after_item_change(booking)
            booking.save(update_fields=['booking_status', 'updated_at'])
    return True, []
