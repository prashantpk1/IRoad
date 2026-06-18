"""Pure truck/driver operational eligibility rules (PCS §6.2.1)."""
from __future__ import annotations

TRUCK_STATUS_ACTIVE = 'Active'
TRUCK_OP_AVAILABLE = 'Available'
DRIVER_STATUS_ACTIVE = 'Active'


def truck_operational_status_value(truck) -> str:
    return (getattr(truck, 'operational_status', '') or '').strip()


def truck_is_available_for_operations(truck) -> bool:
    if truck is None:
        return False
    if getattr(truck, 'status', '') != TRUCK_STATUS_ACTIVE:
        return False
    op = truck_operational_status_value(truck)
    if op and op != TRUCK_OP_AVAILABLE:
        return False
    return True


def driver_is_available_for_operations(driver) -> bool:
    if driver is None:
        return False
    return getattr(driver, 'driver_status', '') == DRIVER_STATUS_ACTIVE


def truck_operational_block_reason(truck) -> str:
    if truck is None:
        return 'Truck not found.'
    if getattr(truck, 'status', '') != TRUCK_STATUS_ACTIVE:
        return 'Truck must be Active.'
    op = truck_operational_status_value(truck)
    if op and op != TRUCK_OP_AVAILABLE:
        return f'Truck operational status is {op}; only Available trucks can be used.'
    return ''


def driver_operational_block_reason(driver) -> str:
    if driver is None:
        return 'Driver not found.'
    if getattr(driver, 'driver_status', '') != DRIVER_STATUS_ACTIVE:
        return 'Driver must be Active.'
    return ''
