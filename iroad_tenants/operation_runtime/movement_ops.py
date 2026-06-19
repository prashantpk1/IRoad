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


def apply_movement_route_map_links(
    movement,
    *,
    from_latitude: str = '',
    from_longitude: str = '',
    to_latitude: str = '',
    to_longitude: str = '',
) -> None:
    """Persist planned route GPS on the truck movement log (TML map-link fields)."""
    if movement is None:
        return
    from iroad_tenants.fleet_gps_tracking import build_google_maps_link

    update_fields: list[str] = []
    from_link = build_google_maps_link(
        (from_latitude or '').strip(),
        (from_longitude or '').strip(),
    )
    to_link = build_google_maps_link(
        (to_latitude or '').strip(),
        (to_longitude or '').strip(),
    )
    if from_link and not (getattr(movement, 'from_location_map_link', '') or '').strip():
        movement.from_location_map_link = from_link[:500]
        update_fields.append('from_location_map_link')
    if to_link and not (getattr(movement, 'to_location_map_link', '') or '').strip():
        movement.to_location_map_link = to_link[:500]
        update_fields.append('to_location_map_link')
    if update_fields:
        update_fields.append('updated_at')
        movement.save(update_fields=update_fields)


def sync_movement_route_evidence_from_action_log(action_log) -> None:
    """
    Copy mobile GPS evidence from an action log row onto the linked TML.

    EM1 (Start) stamps ``from_location_map_link``; EM3/EM4 stamp ``to_location_map_link``.
    Action Log from/to labels still resolve via ``truck_movement`` location masters.
    """
    movement = getattr(action_log, 'truck_movement', None)
    action = getattr(action_log, 'operation_action', None)
    if movement is None or action is None or getattr(action_log, 'shipment_id', None):
        return

    from iroad_tenants.fleet_gps_tracking import build_google_maps_link
    from iroad_tenants.operation_runtime.movement_state_machine import (
        is_movement_arrived_action,
        is_movement_complete_action,
        is_movement_start_action,
    )

    lat = (getattr(action_log, 'latitude', '') or '').strip()
    lng = (getattr(action_log, 'longitude', '') or '').strip()
    map_link = (getattr(action_log, 'map_link', '') or '').strip()
    if not map_link:
        map_link = build_google_maps_link(lat, lng)
    if not map_link:
        return

    update_fields: list[str] = []
    if is_movement_start_action(action) and not (
        getattr(movement, 'from_location_map_link', '') or ''
    ).strip():
        movement.from_location_map_link = map_link[:500]
        update_fields.append('from_location_map_link')
    elif (
        is_movement_arrived_action(action) or is_movement_complete_action(action)
    ) and not (getattr(movement, 'to_location_map_link', '') or '').strip():
        movement.to_location_map_link = map_link[:500]
        update_fields.append('to_location_map_link')

    if update_fields:
        update_fields.append('updated_at')
        movement.save(update_fields=update_fields)


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
