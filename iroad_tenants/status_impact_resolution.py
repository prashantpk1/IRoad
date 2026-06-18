"""PCS §9.3 status impact resolution — pure helpers (no Django imports)."""
from __future__ import annotations

from iroad_tenants.booking_status import (
    BOOKING_HEADER_CANCELLED,
    BOOKING_HEADER_COMPLETED,
    BOOKING_HEADER_CONFIRMED,
    BOOKING_HEADER_DRAFT,
    BOOKING_HEADER_IN_PROGRESS,
    BOOKING_HEADER_PARTIALLY_COMPLETED,
    OPERATION_ACTION_BOOKING_STATUS_CHOICES,
)

STATUS_IMPACT_DO_NOTHING_VALUE = ''
STATUS_IMPACT_DO_NOTHING_LABEL = 'Do Nothing'

# Mirror TenantShipment.ShipmentStatus.choices
OPERATION_ACTION_SHIPMENT_STATUS_CHOICES = (
    ('Loaded', 'Loaded'),
    ('In Transit', 'In Transit'),
    ('At Delivery', 'At Delivery'),
    ('POD Submitted', 'POD Submitted'),
    ('Delivered', 'Delivered'),
    ('Closed', 'Closed'),
    ('Cancelled', 'Cancelled'),
    ('Created', 'Created'),
)

# Mirror TenantTruckMovementLog.Status.choices
OPERATION_ACTION_MOVEMENT_STATUS_CHOICES = (
    ('Scheduled', 'Scheduled'),
    ('In Progress', 'In Progress'),
    ('Completed', 'Completed'),
    ('Cancelled', 'Cancelled'),
)

BOOKING_IMPACT_DISPLAY_BY_KEY = {
    'draft': BOOKING_HEADER_DRAFT,
    'confirmed': BOOKING_HEADER_CONFIRMED,
    'in_progress': BOOKING_HEADER_IN_PROGRESS,
    'partially_completed': BOOKING_HEADER_PARTIALLY_COMPLETED,
    'completed': BOOKING_HEADER_COMPLETED,
    'cancelled': BOOKING_HEADER_CANCELLED,
}

SHIPMENT_STATUS_VALUES = frozenset(value for value, _ in OPERATION_ACTION_SHIPMENT_STATUS_CHOICES)
MOVEMENT_STATUS_VALUES = frozenset(value for value, _ in OPERATION_ACTION_MOVEMENT_STATUS_CHOICES)


def operation_action_booking_status_choices():
    return OPERATION_ACTION_BOOKING_STATUS_CHOICES


def operation_action_shipment_status_choices():
    return OPERATION_ACTION_SHIPMENT_STATUS_CHOICES


def operation_action_movement_status_choices():
    return OPERATION_ACTION_MOVEMENT_STATUS_CHOICES


def resolve_booking_status_impact(raw_value: str | None) -> str | None:
    token = (raw_value or '').strip()
    if not token:
        return None

    if token in BOOKING_IMPACT_DISPLAY_BY_KEY.values():
        for key, label in BOOKING_IMPACT_DISPLAY_BY_KEY.items():
            if label == token:
                return key

    normalized = token.lower().replace('-', '_').replace(' ', '_')
    legacy_map = {
        'draft': 'draft',
        'confirmed': 'confirmed',
        'cancelled': 'cancelled',
        'in_progress': 'in_progress',
        'partially_completed': 'partially_completed',
        'completed': 'completed',
        'in_execution': 'in_progress',
        'executed': 'completed',
        'active': 'confirmed',
    }
    return legacy_map.get(normalized)


def canonical_booking_status_impact_value(raw_value: str | None) -> str:
    impact_key = resolve_booking_status_impact(raw_value)
    if not impact_key:
        return ''
    return BOOKING_IMPACT_DISPLAY_BY_KEY.get(impact_key, '')


def resolve_shipment_status_impact(raw_value: str | None) -> str | None:
    token = (raw_value or '').strip()
    if not token:
        return None
    if token in SHIPMENT_STATUS_VALUES:
        return token
    normalized = token.lower().replace('-', '_').replace(' ', '_')
    alias_map = {
        'loaded': 'Loaded',
        'created': 'Created',
        'in_transit': 'In Transit',
        'at_delivery': 'At Delivery',
        'pod_submitted': 'POD Submitted',
        'delivered': 'Delivered',
        'closed': 'Closed',
        'cancelled': 'Cancelled',
    }
    return alias_map.get(normalized)


def canonical_shipment_status_impact_value(raw_value: str | None) -> str:
    return resolve_shipment_status_impact(raw_value) or ''


def resolve_movement_status_impact(raw_value: str | None) -> str | None:
    token = (raw_value or '').strip()
    if not token:
        return None
    if token in MOVEMENT_STATUS_VALUES:
        return token
    normalized = token.lower().replace('-', '_').replace(' ', '_')
    alias_map = {
        'scheduled': 'Scheduled',
        'in_progress': 'In Progress',
        'completed': 'Completed',
        'cancelled': 'Cancelled',
    }
    return alias_map.get(normalized)


def canonical_movement_status_impact_value(raw_value: str | None) -> str:
    return resolve_movement_status_impact(raw_value) or ''


def is_valid_booking_status_impact(raw_value: str | None) -> bool:
    return resolve_booking_status_impact(raw_value) is not None


def is_valid_shipment_status_impact(raw_value: str | None) -> bool:
    return resolve_shipment_status_impact(raw_value) is not None


def is_valid_movement_status_impact(raw_value: str | None) -> bool:
    return resolve_movement_status_impact(raw_value) is not None
