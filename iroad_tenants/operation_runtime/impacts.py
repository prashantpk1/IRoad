"""Action Master impact resolution (unchanged portal semantics)."""

from __future__ import annotations

from iroad_tenants.status_impact_resolution import (
    canonical_movement_status_impact_value,
    canonical_shipment_status_impact_value,
    is_valid_movement_status_impact,
    is_valid_shipment_status_impact,
    resolve_movement_status_impact as resolve_movement_status_impact_token,
    resolve_shipment_status_impact as resolve_shipment_status_impact_token,
)
from tenant_workspace.models import TenantShipment, TenantTruckMovementLog


def operation_action_matches(action, *needles) -> bool:
    if action is None:
        return False
    label = (
        getattr(action, 'label', '')
        or getattr(action, 'english_label', '')
        or ''
    )
    blob = f'{(getattr(action, "action_code", "") or "")} {label}'.lower()
    return any(needle.lower() in blob for needle in needles)


def resolve_shipment_status_impact(raw_value):
    """Map Action Master shipment_status_impact to TenantShipment.ShipmentStatus."""
    resolved = resolve_shipment_status_impact_token(raw_value)
    if resolved is None:
        return None
    if resolved in {choice[0] for choice in TenantShipment.ShipmentStatus.choices}:
        return resolved
    return None


def resolve_movement_status_impact(raw_value):
    resolved = resolve_movement_status_impact_token(raw_value)
    if resolved is None:
        return None
    if resolved in {choice[0] for choice in TenantTruckMovementLog.Status.choices}:
        return resolved
    return None


__all__ = [
    'operation_action_matches',
    'resolve_shipment_status_impact',
    'resolve_movement_status_impact',
    'canonical_shipment_status_impact_value',
    'canonical_movement_status_impact_value',
    'is_valid_shipment_status_impact',
    'is_valid_movement_status_impact',
]
