"""
mobile_api/job_detail/guards/entity_lookup.py

Resolve shipment / movement rows by UUID primary key or business number.

Must run inside ``schema_context(tenant_schema)`` — tenant isolation is schema-based.
"""
from __future__ import annotations

import uuid
from typing import Any

from tenant_workspace.models import TenantShipment, TenantTruckMovementLog

_SHIPMENT_SELECT = (
    'booking',
    'booking__assigned_truck',
    'booking__booking_line_backload_truck',
    'booking__client_account',
    'booking__route',
    'booking__route__origin_point',
    'booking__route__destination_point',
    'booking__loading_address',
    'booking__delivery_address',
    'driver',
    'client_account',
    'loading_address',
    'delivery_address',
    'truck',
)
_MOVEMENT_SELECT = (
    'booking',
    'booking__route',
    'driver',
    'shipment',
    'shipment__loading_address',
    'shipment__delivery_address',
    'truck',
)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def lookup_shipment_by_reference(reference: str) -> TenantShipment | None:
    """
    Load one shipment by ``shipment_id`` (UUID) or ``shipment_no``.

    Returns None when not found (caller maps to 404).
    """
    token = (reference or '').strip()
    if not token:
        return None
    qs = TenantShipment.objects.select_related(*_SHIPMENT_SELECT)
    if _is_uuid(token):
        return qs.filter(pk=token).first()
    return qs.filter(shipment_no=token).first()


def lookup_movement_by_reference(reference: str) -> TenantTruckMovementLog | None:
    """
    Load one movement by ``movement_id`` (UUID) or ``movement_no``.
    """
    token = (reference or '').strip()
    if not token:
        return None
    qs = TenantTruckMovementLog.objects.select_related(*_MOVEMENT_SELECT)
    if _is_uuid(token):
        return qs.filter(pk=token).first()
    return qs.filter(movement_no=token).first()


def shipment_entity_summary(shipment: Any) -> dict[str, Any]:
    """Minimal serializable shipment identity for resolver output."""
    return {
        'entity_kind': 'shipment',
        'shipment_id': str(getattr(shipment, 'shipment_id', None) or shipment.pk or ''),
        'shipment_no': str(getattr(shipment, 'shipment_no', '') or ''),
        'shipment_status': str(getattr(shipment, 'shipment_status', '') or ''),
        'booking_id': str(
            getattr(shipment, 'booking_id', None)
            or getattr(getattr(shipment, 'booking', None), 'pk', '')
            or ''
        ),
        'driver_id': str(getattr(shipment, 'driver_id', None) or ''),
    }


def movement_entity_summary(movement: Any) -> dict[str, Any]:
    """Minimal serializable movement identity for resolver output."""
    return {
        'entity_kind': 'movement',
        'movement_id': str(getattr(movement, 'movement_id', None) or movement.pk or ''),
        'movement_no': str(getattr(movement, 'movement_no', '') or ''),
        'status': str(getattr(movement, 'status', '') or ''),
        'movement_source': str(getattr(movement, 'movement_source', '') or ''),
        'driver_id': str(getattr(movement, 'driver_id', None) or ''),
        'shipment_id': str(getattr(movement, 'shipment_id', None) or ''),
    }
