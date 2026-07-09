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

_ARRIVAL_ROUTE_FIELDS = (
    'to_latitude',
    'to_longitude',
    'to_location_address',
    'to_location_map_link',
)


def empty_move_arrival_matches_departure(movement) -> bool:
    """True when arrival route fields mirror departure (not a distinct End Job capture)."""
    if movement is None:
        return False
    from_addr = (getattr(movement, 'from_location_address', '') or '').strip().casefold()
    to_addr = (getattr(movement, 'to_location_address', '') or '').strip().casefold()
    from_lat = (getattr(movement, 'from_latitude', '') or '').strip()
    from_lng = (getattr(movement, 'from_longitude', '') or '').strip()
    to_lat = (getattr(movement, 'to_latitude', '') or '').strip()
    to_lng = (getattr(movement, 'to_longitude', '') or '').strip()
    if to_addr and from_addr and to_addr == from_addr:
        return True
    return bool(
        from_lat and from_lng and to_lat and to_lng and from_lat == to_lat and from_lng == to_lng
    )


def clear_stale_empty_move_arrival_fields(movement) -> bool:
    """
    Remove mirrored ``to_*`` route data so End Job cannot reuse Start Job GPS.

    Returns True when any arrival field was cleared.
    """
    if movement is None or not empty_move_arrival_matches_departure(movement):
        return False
    update_fields: list[str] = []
    for field_name in _ARRIVAL_ROUTE_FIELDS:
        if (getattr(movement, field_name, '') or '').strip():
            setattr(movement, field_name, '')
            update_fields.append(field_name)
    if not update_fields:
        return False
    update_fields.append('updated_at')
    movement.save(update_fields=update_fields)
    return True


def apply_movement_endpoint_gps(
    movement,
    side: str,
    *,
    latitude: str = '',
    longitude: str = '',
    map_link: str = '',
    address: str = '',
    overwrite: bool = False,
) -> None:
    """Persist one route endpoint (``from`` departure or ``to`` arrival) when empty."""
    if movement is None:
        return
    if side not in {'from', 'to'}:
        return

    from iroad_tenants.fleet_gps_tracking import build_google_maps_link

    prefix = f'{side}_'
    lat = (latitude or '').strip()[:32]
    lng = (longitude or '').strip()[:32]
    addr = (address or '').strip()[:500]
    link = (map_link or '').strip()[:500]
    if not link and lat and lng:
        link = (build_google_maps_link(lat, lng) or '')[:500]

    update_fields: list[str] = []
    field_map = {
        f'{prefix}latitude': lat,
        f'{prefix}longitude': lng,
        f'{prefix}location_map_link': link,
        f'{prefix}location_address': addr,
    }
    for field_name, value in field_map.items():
        if not value:
            continue
        current = (getattr(movement, field_name, '') or '').strip()
        if current and not overwrite:
            continue
        setattr(movement, field_name, value)
        update_fields.append(field_name)
    if update_fields:
        update_fields.append('updated_at')
        movement.save(update_fields=update_fields)
        if side == 'from':
            clear_stale_empty_move_arrival_fields(movement)


def apply_movement_route_map_links(
    movement,
    *,
    from_latitude: str = '',
    from_longitude: str = '',
    to_latitude: str = '',
    to_longitude: str = '',
    from_address: str = '',
    to_address: str = '',
) -> None:
    """Persist route GPS snapshots on the TML (legacy manual create payloads)."""
    if movement is None:
        return
    apply_movement_endpoint_gps(
        movement,
        'from',
        latitude=from_latitude,
        longitude=from_longitude,
        address=from_address,
    )
    apply_movement_endpoint_gps(
        movement,
        'to',
        latitude=to_latitude,
        longitude=to_longitude,
        address=to_address,
    )
    clear_stale_empty_move_arrival_fields(movement)


def sync_movement_route_evidence_from_action_log(action_log) -> None:
    """
    Copy mobile GPS evidence from an action log row onto the linked TML.

    Empty-move PCS §5.1:
      - First sequence action: departure ``from_*`` GPS + map link
      - Last sequence action: arrival ``to_*`` GPS + map link
    """
    movement = getattr(action_log, 'truck_movement', None)
    action = getattr(action_log, 'operation_action', None)
    if movement is None or action is None or getattr(action_log, 'shipment_id', None):
        return

    from iroad_tenants.fleet_gps_tracking import build_google_maps_link
    from mobile_api.helpers.empty_move_action_resolver import (
        empty_move_route_endpoint_side,
    )

    lat = (getattr(action_log, 'latitude', '') or '').strip()
    lng = (getattr(action_log, 'longitude', '') or '').strip()
    map_link = (getattr(action_log, 'map_link', '') or '').strip()
    if not map_link and lat and lng:
        map_link = build_google_maps_link(lat, lng) or ''
    if not lat and not lng and not map_link:
        return

    address = str(getattr(action_log, '_route_location_address', '') or '').strip()
    side = empty_move_route_endpoint_side(action)
    if side == 'from':
        apply_movement_endpoint_gps(
            movement,
            'from',
            latitude=lat,
            longitude=lng,
            map_link=map_link,
            address=address,
            overwrite=True,
        )
    elif side == 'to':
        existing_addr = (getattr(movement, 'to_location_address', '') or '').strip()
        apply_movement_endpoint_gps(
            movement,
            'to',
            latitude=lat,
            longitude=lng,
            map_link=map_link,
            address=address or existing_addr,
            overwrite=True,
        )
    elif address:
        from iroad_tenants.operation_runtime.movement_action_validator import (
            is_empty_movement,
        )
        from iroad_tenants.operation_runtime.movement_state_machine import (
            is_movement_in_transit_action,
        )

        if is_empty_movement(movement) and is_movement_in_transit_action(action):
            apply_movement_endpoint_gps(
                movement,
                'to',
                address=address,
                overwrite=True,
            )


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
