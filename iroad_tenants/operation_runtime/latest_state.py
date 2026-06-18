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


def validate_shipment_status_transition(shipment, new_status) -> None:
    """Doc §4.6 — gate Delivered on POD compliance and COD collection."""
    if shipment is None or not new_status:
        return
    if new_status != TenantShipment.ShipmentStatus.DELIVERED:
        return
    if not operation_pod_status_is_complete(shipment.pod_status):
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
        derived = resolve_shipment_status_impact(
            getattr(log.operation_action, 'shipment_status_impact', '')
        )
        if derived:
            return derived
    return None


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
    raw = (action.shipment_status_impact or '').strip()
    if not raw:
        return
    new_status = resolve_shipment_status_impact(raw)
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
    if not operation_action_matches(
        action,
        'upload pod',
        'a7',
        'action 7',
        'hard pod',
        'a7h',
        'hard copy',
        'hard-copy',
        'hardcopy',
        'delivery note',
        'confirm loaded',
        'a4',
    ):
        return
    shipment.pod_type = TenantShipment.PodType.HARD
    shipment.save(update_fields=['pod_type', 'updated_at'])


def apply_hard_copy_received_if_needed(*, shipment, action) -> None:
    """Mark physical hard-copy receipt after A7H — not on digital A7 posting."""
    if shipment is None or action is None:
        return
    if not action.hard_copy_collection:
        return
    if not operation_action_matches(
        action,
        'hard pod',
        'a7h',
        'hard copy',
        'hard-copy',
        'hardcopy',
        'hard pod collection',
    ):
        return
    if (getattr(shipment, 'pod_type', None) or '').strip() != TenantShipment.PodType.HARD:
        return
    shipment.pod_status = TenantShipment.PodStatus.COMPLETED
    shipment.save(update_fields=['pod_status', 'updated_at'])
