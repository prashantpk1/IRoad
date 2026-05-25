"""
mobile_api/helpers/operational_status.py

Shared operational status sets and driver-scoped ORM filters for mobile modules.

Aligned with tenant portal rules (``_tenant_shipment_active_statuses`` in
``iroad_tenants.views``) without importing portal views.
"""
from __future__ import annotations

from django.db.models import Q

# Shipment lifecycle — in-flight (aligned with portal ``_tenant_shipment_active_statuses``).
SHIPMENT_ACTIVE_STATUSES: frozenset[str] = frozenset({
    'Loaded',
    'Created',
    'In Transit',
    'At Delivery',
    'POD Submitted',
    'Delivered',
})

SHIPMENT_TERMINAL_STATUSES: frozenset[str] = frozenset({
    'Closed',
    'Cancelled',
})

SHIPMENT_COMPLETED_STATUSES: frozenset[str] = frozenset({
    'Delivered',
    'Closed',
})


def shipment_active_statuses() -> tuple[str, ...]:
    return tuple(SHIPMENT_ACTIVE_STATUSES)


def shipment_completed_statuses() -> tuple[str, ...]:
    return tuple(SHIPMENT_COMPLETED_STATUSES)

# Truck movement — in-flight.
MOVEMENT_ACTIVE_STATUSES: frozenset[str] = frozenset({
    'Scheduled',
    'In Progress',
})

MOVEMENT_COMPLETED_STATUSES: frozenset[str] = frozenset({
    'Completed',
})

MOVEMENT_CANCELLED_STATUSES: frozenset[str] = frozenset({
    'Cancelled',
})

SHIPMENT_CANCELLED_STATUSES: frozenset[str] = frozenset({
    'Cancelled',
})


def movement_active_statuses() -> tuple[str, ...]:
    return tuple(MOVEMENT_ACTIVE_STATUSES)


def movement_completed_statuses() -> tuple[str, ...]:
    return tuple(MOVEMENT_COMPLETED_STATUSES)


def movement_cancelled_statuses() -> tuple[str, ...]:
    return tuple(MOVEMENT_CANCELLED_STATUSES)


def shipment_cancelled_statuses() -> tuple[str, ...]:
    return tuple(SHIPMENT_CANCELLED_STATUSES)


def movement_terminal_statuses() -> tuple[str, ...]:
    """Completed + cancelled movement statuses."""
    return movement_completed_statuses() + movement_cancelled_statuses()


def movement_active_filter_q() -> Q:
    """In-flight movement logs (Scheduled / In Progress)."""
    return Q(status__in=MOVEMENT_ACTIVE_STATUSES)


def movement_completed_filter_q() -> Q:
    return Q(status__in=MOVEMENT_COMPLETED_STATUSES)


def movement_cancelled_filter_q() -> Q:
    return Q(status__in=MOVEMENT_CANCELLED_STATUSES)


def movement_empty_move_filter_q() -> Q:
    """Empty truck moves (source or reason populated)."""
    return Q(movement_source__iexact='empty') | Q(empty_move_reason__gt='')


def movement_tab_filter_q(tab: str) -> Q:
    """
    Operational tab filter for movement job lists.

    ``tab``: ``active`` | ``completed`` | ``cancelled`` | ``all``
    """
    key = (tab or 'active').strip().lower()
    if key == 'active':
        return movement_active_filter_q()
    if key == 'completed':
        return movement_completed_filter_q()
    if key == 'cancelled':
        return movement_cancelled_filter_q()
    return Q()


def driver_shipment_scope_q(driver) -> Q:
    """
    Shipments assigned to this driver on the row or via booking line assignment.
    """
    driver_id = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
    if not driver_id:
        return Q(pk__in=[])
    return Q(driver_id=driver_id) | Q(booking__assigned_driver_id=driver_id)


def driver_movement_scope_q(driver) -> Q:
    """Movement logs for this driver."""
    driver_id = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
    if not driver_id:
        return Q(pk__in=[])
    return Q(driver_id=driver_id)
