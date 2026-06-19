"""Fleet GPS Surveillance — live markers and shipment tracks from mobile action logs."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone

from tenant_workspace.models import (
    TenantOperationActionLog,
    TenantShipment,
    TenantTruckMovementLog,
)

_COORD_RE = re.compile(r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)')

_DEFAULT_CENTER = {'lat': 24.7136, 'lng': 46.6753}

_GPS_LOOKBACK_DAYS = 14

# Live map + detailed tracking: in-progress shipments only (never cancelled/closed/delivered).
_ACTIVE_SHIPMENT_STATUSES = {
    TenantShipment.ShipmentStatus.LOADED,
    TenantShipment.ShipmentStatus.CREATED,
    TenantShipment.ShipmentStatus.IN_TRANSIT,
    TenantShipment.ShipmentStatus.AT_DELIVERY,
    TenantShipment.ShipmentStatus.POD_SUBMITTED,
}

_EXCLUDED_SHIPMENT_STATUSES = {
    TenantShipment.ShipmentStatus.CANCELLED,
    TenantShipment.ShipmentStatus.CLOSED,
    TenantShipment.ShipmentStatus.DELIVERED,
}


def _is_active_shipment(shipment) -> bool:
    if shipment is None:
        return True
    status = (shipment.shipment_status or '').strip()
    return status in _ACTIVE_SHIPMENT_STATUSES


def build_google_maps_link(latitude: str, longitude: str, map_link: str = '') -> str:
    """Build a Google Maps URL from coordinates when map_link is missing."""
    link = (map_link or '').strip()
    if link.lower().startswith(('http://', 'https://')):
        return link
    lat = (latitude or '').strip()
    lng = (longitude or '').strip()
    if _is_valid_lat(lat) and _is_valid_lng(lng):
        return f'https://maps.google.com/?q={lat},{lng}'
    return link


def _is_valid_lat(value: str) -> bool:
    try:
        num = float((value or '').strip())
    except ValueError:
        return False
    return -90.0 <= num <= 90.0


def _is_valid_lng(value: str) -> bool:
    try:
        num = float((value or '').strip())
    except ValueError:
        return False
    return -180.0 <= num <= 180.0


def _coords_from_log(log) -> tuple[float, float] | None:
    lat_raw = (getattr(log, 'latitude', '') or '').strip()
    lng_raw = (getattr(log, 'longitude', '') or '').strip()
    if _is_valid_lat(lat_raw) and _is_valid_lng(lng_raw):
        return float(lat_raw), float(lng_raw)
    map_link = (getattr(log, 'map_link', '') or '').strip()
    if map_link:
        match = _COORD_RE.search(map_link)
        if match:
            lat = float(match.group(1))
            lng = float(match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return lat, lng
    return None


def _coords_from_map_link(map_link: str) -> tuple[float, float] | None:
    return _coords_from_log(
        type('MapLinkRow', (), {'latitude': '', 'longitude': '', 'map_link': map_link})(),
    )


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return '—'
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).strftime('%d/%m/%Y - %I:%M %p')


def _fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return '—'
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).strftime('%I:%M %p')


def _address_label(address) -> str:
    if address is None:
        return '—'
    for attr in ('display_name', 'english_label', 'arabic_label'):
        val = (getattr(address, attr, '') or '').strip()
        if val:
            return val
    return '—'


def _driver_initials(driver) -> str:
    if driver is None:
        return '—'
    name = (driver.english_name or driver.arabic_name or '').strip()
    if not name:
        return 'DR'
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _action_label(log) -> str:
    action = getattr(log, 'operation_action', None)
    if action is not None:
        label = (getattr(action, 'english_label', '') or '').strip()
        if label:
            return label
    return (log.notes or log.log_no or 'Action').strip() or 'Action'


def _marker_tone(shipment_status: str) -> str:
    key = (shipment_status or '').strip().casefold()
    if key in {'at delivery', 'pod submitted'}:
        return 'orange'
    return 'blue'


def _resolve_truck(log):
    if log.truck_id and log.truck:
        return log.truck
    shipment = getattr(log, 'shipment', None)
    if shipment is not None and shipment.truck_id:
        return shipment.truck
    movement = getattr(log, 'truck_movement', None)
    if movement is not None and movement.truck_id:
        return movement.truck
    return None


def _resolve_driver(log):
    if log.driver_id and log.driver:
        return log.driver
    shipment = getattr(log, 'shipment', None)
    if shipment is not None and shipment.driver_id:
        return shipment.driver
    movement = getattr(log, 'truck_movement', None)
    if movement is not None and movement.driver_id:
        return movement.driver
    return None


def _marker_dedupe_key(log) -> str:
    truck = _resolve_truck(log)
    if truck is not None:
        return f'truck:{truck.pk}'
    if log.driver_id:
        return f'driver:{log.driver_id}'
    if log.shipment_id:
        return f'shipment:{log.shipment_id}'
    if log.truck_movement_id:
        return f'movement:{log.truck_movement_id}'
    return f'log:{log.pk}'


def _gps_logs_queryset(*, since=None, limit: int = 800):
    since = since or (timezone.now() - timedelta(days=_GPS_LOOKBACK_DAYS))
    return (
        TenantOperationActionLog.objects.filter(log_date__gte=since)
        .filter(
            Q(source__iexact='Mobile')
            | Q(source_channel__icontains='mobile')
            | Q(shipment__isnull=False)
            | Q(truck_movement__isnull=False)
        )
        .exclude(
            shipment__shipment_status__in=_EXCLUDED_SHIPMENT_STATUSES,
        )
        .exclude(
            truck_movement__shipment__shipment_status__in=_EXCLUDED_SHIPMENT_STATUSES,
        )
        .select_related(
            'truck',
            'driver',
            'shipment',
            'shipment__truck',
            'shipment__driver',
            'shipment__booking',
            'shipment__loading_address',
            'shipment__delivery_address',
            'truck_movement',
            'truck_movement__truck',
            'truck_movement__driver',
            'operation_action',
            'booking',
        )
        .order_by('-log_date', '-created_at')[:limit]
    )


def _build_live_markers(*, marker_limit: int = 25) -> list[dict[str, Any]]:
    live_markers: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for log in _gps_logs_queryset():
        coords = _coords_from_log(log)
        if coords is None:
            continue
        shipment = log.shipment
        if shipment is not None and not _is_active_shipment(shipment):
            continue
        movement = log.truck_movement
        if (
            movement is not None
            and movement.shipment_id
            and movement.shipment is not None
            and not _is_active_shipment(movement.shipment)
        ):
            continue
        dedupe = _marker_dedupe_key(log)
        if dedupe in seen_keys:
            continue
        seen_keys.add(dedupe)

        truck = _resolve_truck(log)
        driver = _resolve_driver(log)
        plate = '—'
        if truck is not None:
            plate = (truck.plate_number or truck.truck_code or 'Truck').strip()
        elif shipment is not None and shipment.truck_id:
            plate = (
                shipment.truck.plate_number or shipment.truck.truck_code or 'Truck'
            ).strip()

        live_markers.append(
            {
                'marker_key': dedupe,
                'truck_id': str(truck.pk) if truck is not None else '',
                'plate': plate,
                'lat': coords[0],
                'lng': coords[1],
                'tone': _marker_tone(
                    shipment.shipment_status if shipment is not None else '',
                ),
                'shipment_no': shipment.shipment_no if shipment is not None else '',
                'shipment_id': str(shipment.pk) if shipment is not None else '',
                'driver': (
                    (driver.english_name or driver.arabic_name) if driver else '—'
                ),
                'status': (
                    (shipment.shipment_status or '').upper()
                    if shipment is not None
                    else (log.source or 'MOBILE').upper()
                ),
                'logged_at': _fmt_dt(log.log_date),
                'source': (log.source or '').strip(),
            }
        )
        if len(live_markers) >= marker_limit:
            break
    return live_markers


def _shipment_trail(shipment) -> tuple[list[dict[str, float]], list[dict[str, str]]]:
    trail: list[dict[str, float]] = []
    history: list[dict[str, str]] = []

    logs = (
        TenantOperationActionLog.objects.filter(
            Q(shipment=shipment)
            | Q(
                truck_movement_id__in=TenantTruckMovementLog.objects.filter(
                    shipment=shipment,
                ).values_list('pk', flat=True),
            )
        )
        .select_related('operation_action')
        .order_by('log_date', 'created_at')
    )

    for log in logs:
        coords = _coords_from_log(log)
        if coords is not None:
            trail.append({'lat': coords[0], 'lng': coords[1]})
        if len(history) < 8:
            history.append(
                {
                    'title': _action_label(log),
                    'time': _fmt_time(log.log_date),
                    'description': (log.notes or shipment.route_display or '—').strip()
                    or '—',
                    'state': 'completed',
                }
            )

    if len(trail) < 2:
        loading = shipment.loading_address
        delivery = shipment.delivery_address
        start = _coords_from_map_link(getattr(loading, 'map_link', '') or '')
        end = _coords_from_map_link(getattr(delivery, 'map_link', '') or '')
        if start and end:
            trail = [
                {'lat': start[0], 'lng': start[1]},
                {'lat': end[0], 'lng': end[1]},
            ]
        elif start:
            trail = [{'lat': start[0], 'lng': start[1]}]
        elif end:
            trail = [{'lat': end[0], 'lng': end[1]}]

    if not trail:
        for log in reversed(list(logs)):
            coords = _coords_from_log(log)
            if coords is not None:
                trail = [{'lat': coords[0], 'lng': coords[1]}]
                break

    if history:
        history[-1]['state'] = 'current'
    return trail, history


def _build_featured_track(
    live_markers: list[dict[str, Any]],
    *,
    focus_shipment_id: str = '',
) -> dict[str, Any] | None:
    priority = [
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.LOADED,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.DELIVERED,
    ]

    candidate_ids: list[str] = []
    focus_id = (focus_shipment_id or '').strip()
    if focus_id:
        focus_row = TenantShipment.objects.filter(pk=focus_id).first()
        if focus_row is not None and _is_active_shipment(focus_row):
            candidate_ids.append(focus_id)

    for marker in live_markers:
        sid = (marker.get('shipment_id') or '').strip()
        if sid and sid not in candidate_ids:
            candidate_ids.append(sid)

    tracking_shipments = (
        TenantShipment.objects.filter(shipment_status__in=_ACTIVE_SHIPMENT_STATUSES)
        .select_related(
            'truck',
            'driver',
            'booking',
            'loading_address',
            'delivery_address',
        )
        .order_by('-updated_at')
    )
    for shipment in tracking_shipments:
        sid = str(shipment.pk)
        if sid not in candidate_ids:
            candidate_ids.append(sid)

    if not candidate_ids:
        return None

    shipments_by_id = {
        str(s.pk): s
        for s in TenantShipment.objects.filter(pk__in=candidate_ids).select_related(
            'truck',
            'driver',
            'booking',
            'loading_address',
            'delivery_address',
        )
    }

    def sort_key(sid: str) -> tuple[int, int]:
        shipment = shipments_by_id.get(sid)
        if shipment is None:
            return len(priority), 999
        status_rank = (
            priority.index(shipment.shipment_status)
            if shipment.shipment_status in priority
            else len(priority)
        )
        trail_len = len(_shipment_trail(shipment)[0])
        return status_rank, -trail_len

    for sid in sorted(candidate_ids, key=sort_key):
        shipment = shipments_by_id.get(sid)
        if shipment is None or not _is_active_shipment(shipment):
            continue
        trail, history = _shipment_trail(shipment)
        if not trail and not history:
            continue

        driver = shipment.driver or _resolve_driver_from_shipment(shipment)
        loading = _address_label(shipment.loading_address)
        delivery = _address_label(shipment.delivery_address)
        if loading == '—' and shipment.booking:
            loading = _address_label(getattr(shipment.booking, 'loading_address', None))
        if delivery == '—' and shipment.booking:
            delivery = _address_label(getattr(shipment.booking, 'delivery_address', None))

        current = trail[-1] if trail else None
        if current is None:
            loading = shipment.loading_address
            delivery = shipment.delivery_address
            start = _coords_from_map_link(getattr(loading, 'map_link', '') or '')
            end = _coords_from_map_link(getattr(delivery, 'map_link', '') or '')
            if start:
                current = {'lat': start[0], 'lng': start[1]}
            elif end:
                current = {'lat': end[0], 'lng': end[1]}
        status_key = (shipment.shipment_status or '').strip().casefold()
        return {
            'shipment_id': str(shipment.pk),
            'shipment_no': shipment.shipment_no,
            'shipment_status': (shipment.shipment_status or '').upper(),
            'on_time': status_key not in {'cancelled', 'closed'},
            'departure_label': loading,
            'departure_time': _fmt_dt(shipment.created_at),
            'arrival_label': delivery,
            'arrival_time': '—',
            'route_display': (shipment.route_display or '').strip() or '—',
            'driver_name': (
                (driver.english_name or driver.arabic_name) if driver else '—'
            ),
            'driver_initials': _driver_initials(driver),
            'driver_plate': (
                (shipment.truck.plate_number if shipment.truck else '') or '—'
            ),
            'trail': trail,
            'current': current,
            'history': history,
        }
    return None


def _resolve_driver_from_shipment(shipment):
    if shipment.driver_id:
        return shipment.driver
    return None


def build_fleet_gps_payload(
    *,
    marker_limit: int = 25,
    focus_shipment_id: str = '',
) -> dict[str, Any]:
    """Build JSON for Fleet GPS Surveillance maps from mobile/driver action logs."""
    live_markers = _build_live_markers(marker_limit=marker_limit)
    featured_track = _build_featured_track(
        live_markers,
        focus_shipment_id=focus_shipment_id,
    )

    if not live_markers and featured_track and featured_track.get('current'):
        cur = featured_track['current']
        live_markers = [
            {
                'marker_key': f"shipment:{featured_track.get('shipment_id', '')}",
                'truck_id': '',
                'plate': featured_track.get('driver_plate') or 'Active',
                'lat': cur['lat'],
                'lng': cur['lng'],
                'tone': 'blue',
                'shipment_no': featured_track.get('shipment_no', ''),
                'shipment_id': featured_track.get('shipment_id', ''),
                'driver': featured_track.get('driver_name', '—'),
                'status': featured_track.get('shipment_status', ''),
                'logged_at': featured_track.get('departure_time', '—'),
                'source': 'Mobile',
            }
        ]

    center = _DEFAULT_CENTER.copy()
    if live_markers:
        center = {'lat': live_markers[0]['lat'], 'lng': live_markers[0]['lng']}
    elif featured_track and featured_track.get('current'):
        cur = featured_track['current']
        center = {'lat': cur['lat'], 'lng': cur['lng']}

    return {
        'default_center': center,
        'live_markers': live_markers,
        'featured_track': featured_track,
        'updated_at': timezone.localtime(timezone.now()).strftime('%I:%M %p'),
        'has_gps_data': bool(live_markers or featured_track),
    }
