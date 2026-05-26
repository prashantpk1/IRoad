"""
mobile_api/job_detail/guards/ownership.py

Object-level driver ownership for explicit job resolution.

Mirrors booking leg / movement assignment rules used elsewhere in mobile execution,
without importing dashboard *selectors* (current-job selection).
"""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import DriverMaster, TenantBooking, TenantShipment

from iroad_tenants.operation_runtime.movement_action_validator import (
    is_empty_movement,
)


def driver_pk(driver: Any) -> Any:
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)


def assert_driver_active(driver: Any) -> str | None:
    """
    Ensure linked ``DriverMaster`` is active.

    Returns error_code when invalid; None when OK.
    """
    if driver is None:
        return 'driver_not_resolved'
    status = str(getattr(driver, 'driver_status', '') or '').strip()
    if status != DriverMaster.Status.ACTIVE:
        return 'driver_inactive'
    return None


def _norm_line_type(value: str | None) -> str:
    return (value or '').strip().casefold()


def driver_owns_shipment_leg(
    driver: Any,
    booking: TenantBooking | Any | None,
    shipment: TenantShipment | Any,
) -> bool:
    """
    Whether the authenticated driver may execute this shipment leg.

    Rules:
      - Direct ``shipment.driver_id`` match, or
      - Booking ``assigned_driver_id`` (outbound / primary), or
      - Booking ``booking_line_backload_driver_id`` for backload/inbound legs.
    """
    pk = driver_pk(driver)
    if pk is None or shipment is None:
        return False

    shipment_driver_id = getattr(shipment, 'driver_id', None)
    if shipment_driver_id and shipment_driver_id == pk:
        return True

    if booking is None:
        return False

    line = _norm_line_type(getattr(shipment, 'booking_item_type', None))
    if line in {'backload', 'inbound'}:
        return getattr(booking, 'booking_line_backload_driver_id', None) == pk

    return getattr(booking, 'assigned_driver_id', None) == pk


def driver_owns_movement(driver: Any, movement: Any) -> bool:
    """Movement ``driver_id`` must match the authenticated driver."""
    pk = driver_pk(driver)
    if pk is None or movement is None:
        return False
    return getattr(movement, 'driver_id', None) == pk


def movement_is_empty_move_job(movement: Any) -> bool:
    """
    Empty-move Job Detail is only for movement-only / empty contexts.

    Rejects laden movements born from shipments (``movement_source=Loaded`` + shipment FK).
    """
    if movement is None:
        return False
    if not is_empty_movement(movement):
        return False
    if getattr(movement, 'shipment_id', None):
        return False
    source = str(getattr(movement, 'movement_source', '') or '').strip().casefold()
    if source == 'loaded':
        return False
    return True


def shipment_is_driver_accessible(shipment: TenantShipment | Any) -> bool:
    """Cancelled shipments are not executable on the driver execution screen."""
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    return status != TenantShipment.ShipmentStatus.CANCELLED


def movement_is_driver_accessible(movement: Any) -> bool:
    """Cancelled movements are not open for driver execution."""
    from tenant_workspace.models import TenantTruckMovementLog

    status = (getattr(movement, 'status', None) or '').strip()
    return status != TenantTruckMovementLog.Status.CANCELLED
