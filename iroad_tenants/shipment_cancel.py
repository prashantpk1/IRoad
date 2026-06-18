"""Shipment cancel (PCS §4.2) — R1 action log, no hard delete."""
from __future__ import annotations

from django.utils import timezone

DB_STATUS_CANCELLED = 'Cancelled'


def resolve_r1_cancel_action():
    from iroad_tenants.operation_runtime.action_master_catalog import PRODUCTION_ACTION_MASTER
    from tenant_workspace.models import TenantOperationAction

    row = TenantOperationAction.objects.filter(action_code__iexact='R1').first()
    if row is not None:
        return row
    spec = next((s for s in PRODUCTION_ACTION_MASTER if s.action_code.upper() == 'R1'), None)
    if spec is None:
        return None
    model_fields = {field.name for field in TenantOperationAction._meta.fields}
    return TenantOperationAction.objects.create(
        action_code=spec.action_code,
        **spec.defaults(model_fields),
    )


def append_shipment_r1_cancel_action_log(
    *,
    shipment,
    created_by_label: str = '',
    tenant_user=None,
    notes: str = '',
):
    """Append R1 cancel entry to the Action Log (PCS §4.2.2)."""
    from iroad_tenants.views import (
        OPERATION_ACTION_LOG_AUTO_FORM_CODE,
        OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
        OPERATION_ACTION_LOG_REF_PREFIX,
        _next_auto_number_for_form,
    )
    from tenant_workspace.models import TenantOperationActionLog

    operation_action = resolve_r1_cancel_action()
    if operation_action is None:
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

    note_text = (notes or '').strip() or 'Shipment cancelled by admin (R1).'
    return TenantOperationActionLog.objects.create(
        log_no=log_no,
        log_sequence=log_sequence,
        log_date=timezone.now(),
        operation_action=operation_action,
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

    previous_status = shipment.shipment_status
    shipment._original_shipment_status = previous_status
    shipment.shipment_status = DB_STATUS_CANCELLED
    shipment.sync_collection_status_for_lifecycle()
    shipment.save()
    append_shipment_r1_cancel_action_log(
        shipment=shipment,
        created_by_label=created_by_label,
        tenant_user=tenant_user,
        notes=notes,
    )
    return True, []
