"""
mobile_api/helpers/job_card_projections.py

Unified lightweight job-card projections for mobile list feeds.

Design rules:
- Flat, mobile-safe dicts (primary fields at top level).
- No portal serializers, no timelines, no deep object trees.
- Optional compact ``route`` / ``truck`` blocks mirror top-level aliases for legacy clients.
"""
from __future__ import annotations

from typing import Any, Literal

from mobile_api.helpers.dashboard_route import build_shipment_route_summary
from mobile_api.helpers.i18n import get_localized_value

JobType = Literal['shipment', 'movement']

_EMPTY_TRUCK: dict[str, Any] = {
    'truck_id': None,
    'truck_code': '',
    'plate_number': '',
    'truck_status': None,
    'sourcing_mode': None,
}

_EMPTY_ROUTE: dict[str, str] = {
    'summary': '',
    'from_label': '',
    'to_label': '',
}

_EMPTY_INDICATORS: dict[str, bool] = {
    'needs_pod': False,
    'needs_cod': False,
    'is_active': False,
    'is_empty_move': False,
}


def iso_job_timestamp(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat().replace('+00:00', 'Z')
    return str(value)


def project_route_from_shipment(shipment, request=None) -> dict[str, str]:
    """Route labels from a shipment row (addresses or ``route_display``)."""
    if shipment is None:
        return dict(_EMPTY_ROUTE)
    block = build_shipment_route_summary(shipment, request)
    return {
        'summary': (block.get('summary') or '').strip(),
        'from_label': (block.get('from_label') or '').strip(),
        'to_label': (block.get('to_label') or '').strip(),
    }


def _location_label(location, request) -> str:
    if location is None:
        return ''
    return get_localized_value(
        request,
        getattr(location, 'location_name_english', None)
        or getattr(location, 'display_label', ''),
        getattr(location, 'location_name_arabic', None)
        or getattr(location, 'display_label', ''),
    ).strip()


def project_route_from_movement(movement, request=None) -> dict[str, str]:
    """Route labels for movements (shipment fallback, else location points)."""
    shipment = getattr(movement, 'shipment', None)
    if shipment is not None:
        return project_route_from_shipment(shipment, request)
    from_label = _location_label(getattr(movement, 'from_location_point', None), request)
    to_label = _location_label(getattr(movement, 'to_location_point', None), request)
    if from_label and to_label:
        summary = f'{from_label} → {to_label}'
    else:
        summary = from_label or to_label or ''
    return {
        'summary': summary,
        'from_label': from_label,
        'to_label': to_label,
    }


def flatten_route_fields(route: dict[str, str] | None) -> dict[str, str]:
    """Top-level route aliases consumed by mobile clients."""
    block = route or _EMPTY_ROUTE
    return {
        'route_summary': block.get('summary', ''),
        'from_location': block.get('from_label', ''),
        'to_location': block.get('to_label', ''),
    }


def project_truck_summary_row(truck, request=None) -> dict[str, Any]:
    """Truck snapshot from ``TruckMaster`` (reuses dashboard helper)."""
    if truck is None:
        return dict(_EMPTY_TRUCK)
    from mobile_api.services.driver_dashboard_current_job import project_truck_summary

    raw = project_truck_summary(truck) or {}
    return {
        'truck_id': raw.get('truck_id'),
        'truck_code': raw.get('truck_code') or '',
        'plate_number': raw.get('plate_number') or '',
        'truck_status': raw.get('truck_status'),
        'sourcing_mode': raw.get('sourcing_mode'),
    }


def flatten_truck_fields(truck: dict[str, Any] | None) -> dict[str, Any]:
    """Top-level truck aliases (flat ``truck_summary`` contract)."""
    block = truck or _EMPTY_TRUCK
    return {
        'truck_id': block.get('truck_id'),
        'truck_code': block.get('truck_code') or '',
        'plate_number': block.get('plate_number') or '',
        'truck_status': block.get('truck_status'),
        'truck_sourcing_mode': block.get('sourcing_mode'),
    }


def project_pod_cod_fields(*, shipment) -> dict[str, str | bool]:
    """POD/COD snapshot for shipment job cards."""
    from mobile_api.services.driver_dashboard_current_job import (
        project_cod_state,
        project_pod_state,
    )

    pod = project_pod_state(shipment=shipment)
    cod = project_cod_state(shipment=shipment)
    return {
        'pod_status': (getattr(shipment, 'pod_status', None) or '').strip(),
        'cod_status': cod.get('collection_status', '') or '',
        'collection_status': cod.get('collection_status', '') or '',
        'is_cod_order': bool(cod.get('is_cod_order')),
        'is_pod_pending': bool(pod.get('needs_attention')),
        'is_cod_pending': bool(
            cod.get('is_cod_order') and cod.get('is_collection_pending')
        ),
    }


def project_operational_indicators(
    *,
    job_type: JobType,
    shipment=None,
    movement=None,
) -> dict[str, bool]:
    """Flat operational indicator flags for list sorting and badges."""
    flags = dict(_EMPTY_INDICATORS)
    if job_type == 'shipment' and shipment is not None:
        pod_cod = project_pod_cod_fields(shipment=shipment)
        flags['needs_pod'] = bool(pod_cod['is_pod_pending'])
        flags['needs_cod'] = bool(pod_cod['is_cod_pending'])
        from mobile_api.helpers.operational_status import SHIPMENT_ACTIVE_STATUSES

        flags['is_active'] = (shipment.shipment_status or '') in SHIPMENT_ACTIVE_STATUSES
        return flags
    if job_type == 'movement' and movement is not None:
        from mobile_api.helpers.operational_status import MOVEMENT_ACTIVE_STATUSES

        flags['is_active'] = (movement.status or '') in MOVEMENT_ACTIVE_STATUSES
        flags['is_empty_move'] = bool(
            (getattr(movement, 'empty_move_reason', None) or '').strip()
            or str(getattr(movement, 'movement_source', '') or '').lower() == 'empty'
        )
    return flags


def resolve_latest_action_for_job_card(
    row,
    *,
    job_type: JobType,
    latest_action_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Prefer batched summary attached by ``hydrate_job_list_page_actions``.

    Never issues per-row log queries.
    """
    if latest_action_summary is not None:
        return latest_action_summary
    from mobile_api.helpers.job_list_action_aggregation import (
        get_row_latest_action_summary,
    )

    return get_row_latest_action_summary(row)


def resolve_next_action_for_job_card(
    row,
    *,
    job_type: JobType,
    shipment=None,
    next_action_hint: str | None = None,
) -> str | None:
    """Prefer batched hint; fallback to pure status-based builder (no queries)."""
    if next_action_hint is not None:
        return next_action_hint
    from mobile_api.helpers.job_list_action_aggregation import get_row_next_action_hint

    cached = get_row_next_action_hint(row)
    if cached is not None:
        return cached
    if job_type == 'shipment':
        from mobile_api.helpers.job_list_next_action import build_shipment_next_action_hint

        return build_shipment_next_action_hint(row)
    from mobile_api.helpers.job_list_next_action import build_movement_next_action_hint

    return build_movement_next_action_hint(row, shipment=shipment)


def _merge_flat_job_card(
    *,
    job_type: JobType,
    job_id: str,
    job_no: str,
    current_status: str,
    route: dict[str, str],
    truck: dict[str, Any],
    indicators: dict[str, bool],
    latest_action_summary: dict[str, Any] | None,
    next_action_hint: str | None,
    updated_at,
    created_at,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the shared flat job-card envelope."""
    card: dict[str, Any] = {
        'job_id': job_id,
        'job_type': job_type,
        'job_no': job_no,
        'current_status': current_status or '',
        'latest_action_summary': latest_action_summary,
        'next_action_hint': next_action_hint,
        'updated_at': iso_job_timestamp(updated_at),
        'created_at': iso_job_timestamp(created_at),
        # Flat operational indicators (primary mobile contract).
        'needs_pod': indicators.get('needs_pod', False),
        'needs_cod': indicators.get('needs_cod', False),
        'is_active': indicators.get('is_active', False),
        'is_empty_move': indicators.get('is_empty_move', False),
        # Compact nested mirrors (optional; same data, no extra queries).
        'route': route,
        'truck': truck,
        'indicators': indicators,
    }
    card.update(flatten_route_fields(route))
    card.update(flatten_truck_fields(truck))
    card.update(extra)
    return card


def build_shipment_job_card_projection(
    shipment,
    *,
    request=None,
    driver=None,
    latest_action_summary: dict[str, Any] | None = None,
    next_action_hint: str | None = None,
) -> dict[str, Any]:
    """Full shipment job card projection (flat + typed extensions)."""
    route = project_route_from_shipment(shipment, request)
    truck = project_truck_summary_row(getattr(shipment, 'truck', None))
    indicators = project_operational_indicators(
        job_type='shipment',
        shipment=shipment,
    )
    pod_cod = project_pod_cod_fields(shipment=shipment)
    booking_no = None
    booking = getattr(shipment, 'booking', None)
    if booking is not None:
        booking_no = getattr(booking, 'booking_no', None)

    shipment_date = None
    if getattr(shipment, 'shipment_date', None):
        shipment_date = shipment.shipment_date.isoformat()

    extra = {
        'shipment_id': str(shipment.shipment_id),
        'shipment_no': shipment.shipment_no,
        'movement_id': None,
        'movement_no': None,
        'booking_no': booking_no,
        'order_type': shipment.order_type or '',
        'pod_status': pod_cod['pod_status'],
        'cod_status': pod_cod['cod_status'],
        'collection_status': pod_cod['collection_status'],
        'is_cod_order': pod_cod['is_cod_order'],
        'is_pod_pending': pod_cod['is_pod_pending'],
        'is_cod_pending': pod_cod['is_cod_pending'],
        'shipment_date': shipment_date,
        'priority': indicators,
    }

    return _merge_flat_job_card(
        job_type='shipment',
        job_id=str(shipment.shipment_id),
        job_no=shipment.shipment_no,
        current_status=shipment.shipment_status or '',
        route=route,
        truck=truck,
        indicators=indicators,
        latest_action_summary=resolve_latest_action_for_job_card(
            shipment,
            job_type='shipment',
            latest_action_summary=latest_action_summary,
        ),
        next_action_hint=resolve_next_action_for_job_card(
            shipment,
            job_type='shipment',
            next_action_hint=next_action_hint,
        ),
        updated_at=shipment.updated_at,
        created_at=shipment.created_at,
        extra=extra,
    )


def build_movement_job_card_projection(
    movement,
    *,
    request=None,
    latest_action_summary: dict[str, Any] | None = None,
    next_action_hint: str | None = None,
) -> dict[str, Any]:
    """Full movement job card projection (flat + typed extensions)."""
    route = project_route_from_movement(movement, request)
    truck = project_truck_summary_row(getattr(movement, 'truck', None))
    indicators = project_operational_indicators(
        job_type='movement',
        movement=movement,
    )
    shipment = getattr(movement, 'shipment', None)
    shipment_id = None
    shipment_no = None
    if shipment is not None:
        shipment_id = str(shipment.shipment_id)
        shipment_no = shipment.shipment_no

    movement_date = None
    if getattr(movement, 'movement_date', None):
        movement_date = movement.movement_date.isoformat()

    extra = {
        'shipment_id': shipment_id,
        'shipment_no': shipment_no,
        'movement_id': str(movement.movement_id),
        'movement_no': movement.movement_no,
        'movement_source': getattr(movement, 'movement_source', None) or '',
        'empty_move_reason': getattr(movement, 'empty_move_reason', None) or '',
        'is_empty_move': indicators.get('is_empty_move', False),
        'movement_date': movement_date,
        'pod_status': '',
        'cod_status': '',
        'collection_status': '',
        'priority': indicators,
    }

    return _merge_flat_job_card(
        job_type='movement',
        job_id=str(movement.movement_id),
        job_no=movement.movement_no,
        current_status=movement.status or '',
        route=route,
        truck=truck,
        indicators=indicators,
        latest_action_summary=resolve_latest_action_for_job_card(
            movement,
            job_type='movement',
            latest_action_summary=latest_action_summary,
        ),
        next_action_hint=resolve_next_action_for_job_card(
            movement,
            job_type='movement',
            shipment=shipment,
            next_action_hint=next_action_hint,
        ),
        updated_at=movement.updated_at,
        created_at=movement.created_at,
        extra=extra,
    )
