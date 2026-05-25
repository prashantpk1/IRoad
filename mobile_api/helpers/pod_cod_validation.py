"""
Compliance gates for mobile POD upload and COD collection.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from iroad_tenants.services.operation_execution_service import OperationExecutionService
from mobile_api.helpers.action_log_media import count_media_attachments
from mobile_api.services.driver_dashboard_current_job import fetch_active_movement
from mobile_api.services.driver_job_allowed_actions_service import (
    DriverJobAllowedActionsService,
)
from tenant_workspace.models import TenantShipment, TenantShipmentDocument


_TERMINAL_SHIPMENT_STATUSES = {
    TenantShipment.ShipmentStatus.CLOSED,
    TenantShipment.ShipmentStatus.CANCELLED,
}


def _policy_error_message(policy_error: str | None) -> str:
    return (policy_error or '').strip() or _('mobile.jobs.compliance.action_not_allowed')


def validate_shipment_compliance_context(
    *,
    shipment,
    driver,
    operation_action,
) -> None:
    if shipment is None:
        raise ValidationError(_('mobile.jobs.detail.shipment_not_found'))
    if operation_action is None:
        raise ValidationError(_('mobile.jobs.compliance.action_not_configured'))

    current = shipment.shipment_status or ''
    if current in _TERMINAL_SHIPMENT_STATUSES:
        raise ValidationError(_('mobile.jobs.compliance.shipment_terminal'))

    movement = fetch_active_movement(driver=driver, shipment=shipment)
    booking, shipment, movement, booking_item_type = (
        DriverJobAllowedActionsService._resolve_linkage(
            shipment=shipment,
            movement=movement,
        )
    )
    policy_error = OperationExecutionService.validate_driver_action_execution(
        operation_action,
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
    )
    if policy_error:
        raise ValidationError(_policy_error_message(policy_error))


def validate_pod_upload_compliance(
    *,
    shipment,
    driver,
    operation_action,
    request=None,
) -> None:
    validate_shipment_compliance_context(
        shipment=shipment,
        driver=driver,
        operation_action=operation_action,
    )

    has_dn = TenantShipmentDocument.objects.filter(
        shipment_id=shipment.pk,
        is_delivery_note=True,
    ).exists()
    if not has_dn:
        raise ValidationError(_('mobile.jobs.pod.delivery_note_required'))

    if request is not None and count_media_attachments(request) < 1:
        raise ValidationError(_('mobile.jobs.pod.photo_required'))


def _parse_cod_amount(raw, *, shipment) -> Decimal:
    if raw is None or raw == '':
        raw = shipment.cod_amount
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(_('mobile.jobs.execute.invalid_cod_amount'))
    if value <= 0:
        raise ValidationError(_('mobile.jobs.execute.cod_amount_required'))
    return value


def validate_cod_collection_compliance(
    *,
    shipment,
    driver,
    operation_action,
    cod_amount_raw=None,
) -> Decimal:
    validate_shipment_compliance_context(
        shipment=shipment,
        driver=driver,
        operation_action=operation_action,
    )

    if (shipment.order_type or '').upper() != 'COD':
        raise ValidationError(_('mobile.jobs.cod.not_cod_shipment'))

    if shipment.collection_status == TenantShipment.CollectionStatus.COLLECTED:
        raise ValidationError(_('mobile.jobs.cod.already_collected'))

    return _parse_cod_amount(cod_amount_raw, shipment=shipment)
