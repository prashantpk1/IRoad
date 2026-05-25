"""Action Master impact resolution (unchanged portal semantics)."""

from __future__ import annotations

from tenant_workspace.models import TenantShipment, TenantTruckMovementLog


def operation_action_matches(action, *needles) -> bool:
    if action is None:
        return False
    blob = f'{(action.action_code or "")} {(action.english_label or "")}'.lower()
    return any(needle.lower() in blob for needle in needles)


def resolve_shipment_status_impact(raw_value):
    """Map Action Master shipment_status_impact to TenantShipment.ShipmentStatus."""
    token = (raw_value or '').strip()
    if not token:
        return None
    if token in {choice[0] for choice in TenantShipment.ShipmentStatus.choices}:
        return token
    normalized = token.lower().replace('-', '_').replace(' ', '_')
    alias_map = {
        'loaded': TenantShipment.ShipmentStatus.LOADED,
        'created': TenantShipment.ShipmentStatus.CREATED,
        'in_transit': TenantShipment.ShipmentStatus.IN_TRANSIT,
        'at_delivery': TenantShipment.ShipmentStatus.AT_DELIVERY,
        'pod_submitted': TenantShipment.ShipmentStatus.POD_SUBMITTED,
        'delivered': TenantShipment.ShipmentStatus.DELIVERED,
        'closed': TenantShipment.ShipmentStatus.CLOSED,
        'cancelled': TenantShipment.ShipmentStatus.CANCELLED,
    }
    return alias_map.get(normalized)


def resolve_movement_status_impact(raw_value):
    token = (raw_value or '').strip()
    if not token:
        return None
    if token in {choice[0] for choice in TenantTruckMovementLog.Status.choices}:
        return token
    normalized = token.lower().replace('-', '_').replace(' ', '_')
    alias_map = {
        'scheduled': TenantTruckMovementLog.Status.SCHEDULED,
        'in_progress': TenantTruckMovementLog.Status.IN_PROGRESS,
        'completed': TenantTruckMovementLog.Status.COMPLETED,
        'cancelled': TenantTruckMovementLog.Status.CANCELLED,
    }
    return alias_map.get(normalized)
