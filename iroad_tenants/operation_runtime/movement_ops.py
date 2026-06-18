"""Truck movement side effects for shipment execution."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from iroad_tenants.operation_runtime.constants import (
    TRUCK_MOVEMENT_LOG_AUTO_FORM_CODE,
    TRUCK_MOVEMENT_LOG_AUTO_FORM_LABEL,
    TRUCK_MOVEMENT_LOG_REF_PREFIX,
)
from tenant_workspace.models import TenantShipment, TenantTruckMovementLog

VALID_EMPTY_MOVE_REASONS = frozenset({'reposition', 'maintenance', 'noLoad'})


def auto_complete_loaded_movement_for_shipment(shipment):
    """Complete open Loaded movement when shipment is Delivered."""
    if shipment is None:
        return None
    movement = (
        TenantTruckMovementLog.objects.filter(shipment_id=shipment.pk)
        .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
        .order_by('-created_at')
        .first()
    )
    if movement is None:
        return None
    if movement.status == TenantTruckMovementLog.Status.COMPLETED:
        return movement
    movement.status = TenantTruckMovementLog.Status.COMPLETED
    movement.end_time = timezone.now()
    movement.save(update_fields=['status', 'end_time', 'updated_at'])
    return movement


def birth_movement_for_shipment(shipment, *, movement_date=None, created_by_label=''):
    """Truck movement born with shipment at Confirm Loaded (doc §4.4)."""
    existing = (
        TenantTruckMovementLog.objects.filter(shipment_id=shipment.pk)
        .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
        .order_by('-created_at')
        .first()
    )
    if existing is not None:
        return existing
    movement_date = movement_date or shipment.shipment_date or timezone.localdate()
    from iroad_tenants.views import _next_auto_number_for_form

    movement_no, movement_sequence = _next_auto_number_for_form(
        form_code=TRUCK_MOVEMENT_LOG_AUTO_FORM_CODE,
        form_label=TRUCK_MOVEMENT_LOG_AUTO_FORM_LABEL,
        prefix=TRUCK_MOVEMENT_LOG_REF_PREFIX,
    )
    movement = TenantTruckMovementLog(
        movement_no=movement_no,
        movement_sequence=movement_sequence,
        movement_date=movement_date,
        movement_source='Loaded',
        status=TenantTruckMovementLog.Status.SCHEDULED,
        booking=shipment.booking,
        shipment=shipment,
        truck=shipment.truck,
        driver=shipment.driver,
        created_by_label=(created_by_label or '')[:200],
    )
    movement.save()
    return movement


def birth_empty_move_for_driver(
    *,
    driver,
    truck,
    from_location,
    to_location,
    empty_move_reason: str,
    movement_date=None,
    notes: str = '',
    created_by_label: str = '',
    distance_km=None,
) -> TenantTruckMovementLog:
    """
    Create a standalone empty truck movement for the driver mobile app.

    Status starts at Scheduled; EM1 transitions to In Progress.
    """
    reason = (empty_move_reason or '').strip()
    if reason not in VALID_EMPTY_MOVE_REASONS:
        raise ValueError('Invalid empty move reason.')

    movement_date = movement_date or timezone.localdate()
    from iroad_tenants.views import (
        _next_auto_number_for_form,
        _tenant_truck_movement_lookup_route_distance,
    )

    movement_no, movement_sequence = _next_auto_number_for_form(
        form_code=TRUCK_MOVEMENT_LOG_AUTO_FORM_CODE,
        form_label=TRUCK_MOVEMENT_LOG_AUTO_FORM_LABEL,
        prefix=TRUCK_MOVEMENT_LOG_REF_PREFIX,
    )

    resolved_distance = distance_km
    if resolved_distance is None:
        looked_up = _tenant_truck_movement_lookup_route_distance(
            from_location,
            to_location,
        )
        resolved_distance = looked_up if looked_up is not None else Decimal('0')

    movement = TenantTruckMovementLog(
        movement_no=movement_no,
        movement_sequence=movement_sequence,
        movement_date=movement_date,
        movement_source='empty',
        empty_move_reason=reason,
        status=TenantTruckMovementLog.Status.SCHEDULED,
        booking=None,
        shipment=None,
        truck=truck,
        driver=driver,
        from_location_point=from_location,
        to_location_point=to_location,
        distance_km=resolved_distance,
        notes=(notes or '')[:5000],
        created_by_label=(created_by_label or '')[:200],
    )
    movement.save()
    return movement
