"""
mobile_api/job_detail/guards/entity_lookup.py

Resolve shipment / movement rows by UUID primary key or business number.

Must run inside ``schema_context(tenant_schema)`` — tenant isolation is schema-based.
"""
from __future__ import annotations

import uuid
from typing import Any

from tenant_workspace.models import TenantBooking, TenantShipment, TenantTruckMovementLog

_BOOKING_SELECT = (
    'client_account',
    'route',
    'route__origin_point',
    'route__destination_point',
    'loading_address',
    'delivery_address',
    'assigned_truck',
    'assigned_driver',
)

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

# Tenant schemas may lag migration 0106; defer optional column so mobile lookups
# do not fail when ``tenant_address_master.extension`` is not migrated yet.
_BOOKING_ADDRESS_DEFER = (
    'loading_address__extension',
    'delivery_address__extension',
)
_SHIPMENT_ADDRESS_DEFER = (
    'loading_address__extension',
    'delivery_address__extension',
    'booking__loading_address__extension',
    'booking__delivery_address__extension',
)
_MOVEMENT_ADDRESS_DEFER = (
    'shipment__loading_address__extension',
    'shipment__delivery_address__extension',
)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def lookup_booking_by_reference(reference: str) -> TenantBooking | None:
    """Load one booking by ``booking_id`` (UUID) or ``booking_no``."""
    token = (reference or '').strip()
    if not token:
        return None
    qs = TenantBooking.objects.select_related(*_BOOKING_SELECT).defer(
        *_BOOKING_ADDRESS_DEFER,
    )
    if _is_uuid(token):
        return qs.filter(pk=token).first()
    return qs.filter(booking_no=token).first()


def lookup_shipment_by_reference(reference: str) -> TenantShipment | None:
    """
    Load one shipment by ``shipment_id`` (UUID) or ``shipment_no``.

    Returns None when not found (caller maps to 404).
    """
    token = (reference or '').strip()
    if not token:
        return None
    qs = TenantShipment.objects.select_related(*_SHIPMENT_SELECT).defer(
        *_SHIPMENT_ADDRESS_DEFER,
    )
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
    qs = TenantTruckMovementLog.objects.select_related(*_MOVEMENT_SELECT).defer(
        *_MOVEMENT_ADDRESS_DEFER,
    )
    if _is_uuid(token):
        return qs.filter(pk=token).first()
    return qs.filter(movement_no=token).first()


def booking_entity_summary(booking: Any) -> dict[str, Any]:
    """Minimal serializable booking identity for resolver output."""
    return {
        'entity_kind': 'booking',
        'booking_id': str(getattr(booking, 'booking_id', None) or booking.pk or ''),
        'booking_no': str(getattr(booking, 'booking_no', '') or ''),
        'booking_status': str(getattr(booking, 'booking_status', '') or ''),
        'assigned_driver_id': str(getattr(booking, 'assigned_driver_id', None) or ''),
    }


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
