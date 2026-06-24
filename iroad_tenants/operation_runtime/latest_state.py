"""Hybrid shipment status cache derived from action logs."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from iroad_tenants.operation_field_catalog import operation_pod_status_is_complete
from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_shipment_status_impact,
)
from iroad_tenants.operation_runtime.movement_ops import (
    auto_complete_loaded_movement_for_shipment,
)
from tenant_workspace.models import TenantOperationActionLog, TenantShipment


def resolve_effective_shipment_status_for_action(*, action, shipment=None):
    """
    Status column written when an action executes.

    Upload POD (``auto_pod_post``) must advance to POD Submitted, not Delivered.
    Delivered is reserved for post-POD/COD auto-verify (``A_POD_VERIFY``) or
    collect-payment side effects — misconfigured Action Master rows with
    ``Delivered`` on POD upload are normalized here.
    """
    _ = shipment
    raw = (getattr(action, 'shipment_status_impact', None) or '').strip()
    if not raw:
        return None
    new_status = resolve_shipment_status_impact(raw)
    if not new_status:
        return None
    if (
        new_status == TenantShipment.ShipmentStatus.DELIVERED
        and getattr(action, 'auto_pod_post', False)
    ):
        return TenantShipment.ShipmentStatus.POD_SUBMITTED
    return new_status


def validate_shipment_status_transition(shipment, new_status) -> None:
    """Doc §4.6 — gate Delivered on POD compliance and COD collection."""
    if shipment is None or not new_status:
        return
    if new_status != TenantShipment.ShipmentStatus.DELIVERED:
        return
    if not operation_pod_status_is_complete(shipment.pod_status):
        pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
        hard_pod_deliverable = False
        if pod_type == TenantShipment.PodType.HARD.casefold():
            from iroad_tenants.operation_runtime.side_effects import (
                _mobile_log_evidence_for_shipment,
            )

            evidence = _mobile_log_evidence_for_shipment(shipment)
            hard_pod_deliverable = bool(evidence.get('hard_pod_log'))
        if not hard_pod_deliverable:
            raise ValidationError(
                'Shipment cannot move to Delivered until POD is compliant '
                '(all delivery-note documents verified).'
            )
    if shipment.order_type.upper() == 'COD':
        if shipment.collection_status != TenantShipment.CollectionStatus.COLLECTED:
            raise ValidationError(
                'COD shipment cannot move to Delivered until payment is collected.'
            )


def after_shipment_status_side_effects(shipment) -> None:
    if shipment is None:
        return
    if shipment.shipment_status in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }:
        auto_complete_loaded_movement_for_shipment(shipment)
    from iroad_tenants.views import _tenant_shipment_document_refresh_shipment_pod

    _tenant_shipment_document_refresh_shipment_pod(shipment)
    if shipment.shipment_status in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    }:
        from iroad_tenants.operation_runtime.side_effects import (
            _sync_pod_status_from_mobile_logs,
            sync_booking_pod_status_from_shipments,
        )

        _sync_pod_status_from_mobile_logs(shipment)
        booking = getattr(shipment, 'booking', None)
        if booking is None and shipment.booking_id:
            from tenant_workspace.models import TenantBooking

            booking = TenantBooking.objects.filter(pk=shipment.booking_id).first()
        sync_booking_pod_status_from_shipments(booking)


def derive_latest_action_status(shipment):
    if shipment is None:
        return None
    latest_logs = (
        TenantOperationActionLog.objects.filter(shipment_id=shipment.pk)
        .select_related('operation_action')
        .exclude(operation_action__isnull=True)
        .order_by('-log_date', '-created_at')[:50]
    )
    for log in latest_logs:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        derived = resolve_effective_shipment_status_for_action(
            action=action,
            shipment=shipment,
        )
        if derived:
            return derived
    return None


def repair_delivered_before_hard_pod_custody(shipment) -> bool:
    """
    Rewind Delivered → POD Submitted when digital POD is done but hard-copy
    custody is still outstanding (misconfigured POD upload impact or legacy logs).
    """
    if shipment is None:
        return False
    current = (getattr(shipment, 'shipment_status', None) or '').strip()
    if current != TenantShipment.ShipmentStatus.DELIVERED:
        return False
    try:
        from mobile_api.dashboard.selectors.pod_cod_policy import derive_hard_pod_pending

        if not derive_hard_pod_pending(shipment):
            return False
    except Exception:
        return False
    shipment.shipment_status = TenantShipment.ShipmentStatus.POD_SUBMITTED
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    return True


def sync_shipment_status_from_action_log(shipment):
    """
    Gap 4 (hybrid): keep shipment_status column as cache, derive from latest action log.
    """
    if shipment is None:
        return shipment
    derived_status = derive_latest_action_status(shipment)
    if not derived_status or shipment.shipment_status == derived_status:
        return shipment
    shipment.shipment_status = derived_status
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    after_shipment_status_side_effects(shipment)
    return shipment


def apply_shipment_status_impact(*, shipment, action, created_by_label: str = '') -> None:
    """Apply shipment_status_impact with validation and follow-on effects."""
    if shipment is None or action is None:
        return
    new_status = resolve_effective_shipment_status_for_action(
        action=action,
        shipment=shipment,
    )
    if not new_status:
        return
    validate_shipment_status_transition(shipment, new_status)
    shipment.shipment_status = new_status
    shipment.save(update_fields=['shipment_status', 'updated_at'])
    after_shipment_status_side_effects(shipment)


def apply_hard_copy_pod_type_if_needed(*, shipment, action) -> None:
    if shipment is None or action is None:
        return
    if not action.hard_copy_collection:
        return
    from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod

    if not operation_shipment_uses_hard_copy_pod(shipment):
        return
    shipment.pod_type = TenantShipment.PodType.HARD
    shipment.save(update_fields=['pod_type', 'updated_at'])


def apply_hard_copy_received_if_needed(*, shipment, action) -> None:
    """Mark physical hard-copy receipt after hard-copy collection execute."""
    if shipment is None or action is None:
        return
    if not action.hard_copy_collection:
        return
    if (getattr(shipment, 'pod_type', None) or '').strip() != TenantShipment.PodType.HARD:
        return
    # Combined POD actions may execute hard custody before digital evidence.
    if getattr(action, 'auto_pod_post', False):
        from iroad_tenants.operation_runtime.side_effects import (
            _mobile_log_evidence_for_shipment,
        )

        evidence = _mobile_log_evidence_for_shipment(shipment)
        if not evidence.get('pod_uploaded'):
            return
    shipment.pod_status = TenantShipment.PodStatus.COMPLETED
    shipment.save(update_fields=['pod_status', 'updated_at'])
