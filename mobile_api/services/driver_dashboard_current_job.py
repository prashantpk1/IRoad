"""
mobile_api/services/driver_dashboard_current_job.py

Lightweight current operational snapshot for the driver home dashboard.

Query budget (active job present): 1 shipment + ≤2 movements + 1 latest action log.
No timelines, no bulk log scans, no portal detail views.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from mobile_api.helpers.dashboard_route import build_shipment_route_summary
from mobile_api.helpers.i18n import get_localized_value
from mobile_api.helpers.dashboard_security import (
    assert_movement_row_owned,
    assert_shipment_row_owned,
    movement_queryset_for_driver,
    shipment_queryset_for_driver,
)
from mobile_api.helpers.operational_status import (
    MOVEMENT_ACTIVE_STATUSES,
    shipment_active_statuses,
)

_ACTIVE_SHIPMENT_STATUSES = shipment_active_statuses()
_MOVEMENT_ACTIVE = tuple(MOVEMENT_ACTIVE_STATUSES)

_SHIPMENT_LOOKUP_RELATED = (
    'truck',
    'booking',
    'loading_address',
    'delivery_address',
)

_ACTION_LOG_ONLY = (
    'log_id',
    'log_no',
    'log_date',
    'operation_action_id',
)


def empty_current_job_snapshot() -> dict[str, Any]:
    return {
        'has_active_job': False,
        'shipment': None,
        'movement': None,
        'status': None,
        'route': None,
        'truck': None,
        'latest_action': None,
        'pod': None,
        'cod': None,
        'next_action_hint': None,
        'shipment_id': None,
        'shipment_no': None,
        'shipment_status': None,
        'booking_no': None,
        'route_summary': '',
        'pod_status': None,
        'collection_status': None,
        'order_type': None,
        'operational_stage': None,
    }


_SHIPMENT_CURRENT_JOB_ONLY = (
    'shipment_id',
    'shipment_no',
    'shipment_status',
    'shipment_date',
    'order_type',
    'sourcing_mode',
    'pod_status',
    'pod_type',
    'collection_status',
    'cod_amount',
    'booking_id',
    'truck_id',
    'loading_address_id',
    'delivery_address_id',
)


def fetch_latest_active_shipment(*, driver):
    """Most recently updated in-flight shipment for this driver."""
    return (
        shipment_queryset_for_driver(driver)
        .filter(shipment_status__in=_ACTIVE_SHIPMENT_STATUSES)
        .only(*_SHIPMENT_CURRENT_JOB_ONLY)
        .select_related(*_SHIPMENT_LOOKUP_RELATED)
        .order_by('-updated_at', '-created_at')
        .first()
    )


def fetch_active_movement(*, driver, shipment) -> Any:
    """Active movement tied to the shipment, else latest driver active movement."""
    from tenant_workspace.models import TenantTruckMovementLog

    base = TenantTruckMovementLog.objects.filter(
        driver_movement_scope_q(driver),
        status__in=_MOVEMENT_ACTIVE,
    ).only(
        'movement_id',
        'movement_no',
        'status',
        'movement_date',
        'movement_source',
        'shipment_id',
        'updated_at',
    )

    if shipment is not None:
        linked = base.filter(shipment_id=shipment.pk).order_by('-updated_at').first()
        if linked is not None:
            return linked

    return base.order_by('-updated_at').first()


def fetch_latest_action_log(*, driver, shipment) -> Any:
    """Single latest action log row for the active shipment (not a timeline scan)."""
    from tenant_workspace.models import TenantOperationActionLog

    if shipment is None:
        return None

    return (
        TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
            driver_id=driver.pk,
        )
        .only(*_ACTION_LOG_ONLY)
        .select_related('operation_action')
        .order_by('-log_date', '-created_at')
        .first()
    )


def project_truck_summary(truck) -> dict[str, Any] | None:
    if truck is None:
        return None
    return {
        'truck_id': str(truck.truck_id),
        'truck_code': truck.truck_code or '',
        'plate_number': truck.plate_number or '',
        'truck_status': getattr(truck, 'status', None),
        'sourcing_mode': getattr(truck, 'sourcing_mode', None),
    }


def project_shipment_summary(*, shipment) -> dict[str, Any]:
    booking_no = None
    if shipment.booking_id and getattr(shipment, 'booking', None):
        booking_no = shipment.booking.booking_no

    shipment_date = None
    if shipment.shipment_date:
        shipment_date = shipment.shipment_date.isoformat()

    return {
        'shipment_id': str(shipment.shipment_id),
        'shipment_no': shipment.shipment_no,
        'shipment_status': shipment.shipment_status,
        'booking_no': booking_no,
        'order_type': shipment.order_type or '',
        'sourcing_mode': shipment.sourcing_mode or '',
        'shipment_date': shipment_date,
    }


def project_movement_summary(movement) -> dict[str, Any] | None:
    if movement is None:
        return None
    return {
        'movement_id': str(movement.movement_id),
        'movement_no': movement.movement_no,
        'status': movement.status,
        'movement_date': movement.movement_date.isoformat()
        if movement.movement_date
        else None,
        'movement_source': getattr(movement, 'movement_source', None) or '',
    }


def project_latest_action_summary(log_row, request=None) -> dict[str, Any] | None:
    if log_row is None:
        return None
    action = getattr(log_row, 'operation_action', None)
    code = None
    label = ''
    if action is not None:
        code = action.action_code
        label = get_localized_value(
            request,
            getattr(action, 'english_label', '') or code or '',
            getattr(action, 'arabic_label', '') or '',
        )
    return {
        'log_id': str(log_row.log_id),
        'log_no': log_row.log_no,
        'log_date': log_row.log_date.isoformat() if log_row.log_date else None,
        'action_code': code,
        'action_label': label or None,
    }


def project_pod_state(*, shipment) -> dict[str, Any]:
    from tenant_workspace.models import TenantShipment

    status = shipment.pod_status or ''
    compliant = TenantShipment.PodStatus.COMPLIANT
    pending = TenantShipment.PodStatus.PENDING
    return {
        'status': status,
        'is_pending': status == pending,
        'needs_attention': status != compliant,
        'pod_type': getattr(shipment, 'pod_type', None) or '',
    }


def project_cod_state(*, shipment) -> dict[str, Any]:
    from tenant_workspace.models import TenantShipment

    order_type = (shipment.order_type or '').strip()
    amount = shipment.cod_amount
    collection_status = shipment.collection_status or ''
    is_cod = order_type.upper() == 'COD' or (amount and amount > 0)
    return {
        'order_type': order_type,
        'cod_amount': str(amount) if amount is not None else '0',
        'collection_status': collection_status,
        'is_cod_order': is_cod,
        'is_collection_pending': (
            is_cod and collection_status == TenantShipment.CollectionStatus.PENDING
        ),
    }


def project_status_summary(*, shipment, movement) -> dict[str, Any]:
    movement_status = movement.status if movement is not None else None
    return {
        'shipment_status': shipment.shipment_status,
        'movement_status': movement_status,
        'operational_stage': shipment.shipment_status,
        'has_active_movement': movement is not None,
    }


def build_next_action_hint(*, shipment) -> str | None:
    from tenant_workspace.models import TenantShipment

    pod = project_pod_state(shipment=shipment)
    cod = project_cod_state(shipment=shipment)

    if pod['needs_attention']:
        return str(_('mobile.dashboard.next_action.pod'))
    if cod['is_cod_order'] and cod['is_collection_pending']:
        return str(_('mobile.dashboard.next_action.cod'))
    status = str(shipment.shipment_status)
    if status in (
        TenantShipment.ShipmentStatus.LOADED,
        TenantShipment.ShipmentStatus.CREATED,
    ):
        return str(_('mobile.dashboard.next_action.transit'))
    if status == TenantShipment.ShipmentStatus.AT_DELIVERY:
        return str(_('mobile.dashboard.next_action.deliver'))
    if status == TenantShipment.ShipmentStatus.POD_SUBMITTED:
        return str(_('mobile.dashboard.next_action.pod_review'))
    return None


def build_current_job_snapshot(
    *,
    driver,
    request=None,
    latest_shipment=None,
    build_state=None,
) -> dict[str, Any]:
    """
    Assemble ``data.current_job`` with nested projections and flat aliases.
    """
    if latest_shipment is not None:
        shipment = latest_shipment
    elif build_state is not None:
        shipment = build_state.get_latest_active_shipment(
            fetcher=fetch_latest_active_shipment,
        )
    else:
        shipment = fetch_latest_active_shipment(driver=driver)
    if shipment is None or not assert_shipment_row_owned(driver, shipment):
        return empty_current_job_snapshot()

    movement = fetch_active_movement(driver=driver, shipment=shipment)
    if movement is not None and not assert_movement_row_owned(driver, movement):
        movement = None
    latest_log = fetch_latest_action_log(driver=driver, shipment=shipment)

    shipment_block = project_shipment_summary(shipment=shipment)
    movement_block = project_movement_summary(movement)
    route_block = build_shipment_route_summary(shipment, request)
    truck_block = project_truck_summary(shipment.truck)
    latest_action_block = project_latest_action_summary(latest_log, request)
    pod_block = project_pod_state(shipment=shipment)
    cod_block = project_cod_state(shipment=shipment)
    status_block = project_status_summary(shipment=shipment, movement=movement)
    next_hint = build_next_action_hint(shipment=shipment)

    return {
        'has_active_job': True,
        'shipment': shipment_block,
        'movement': movement_block,
        'status': status_block,
        'route': route_block,
        'truck': truck_block,
        'latest_action': latest_action_block,
        'pod': pod_block,
        'cod': cod_block,
        'next_action_hint': next_hint,
        'shipment_id': shipment_block['shipment_id'],
        'shipment_no': shipment_block['shipment_no'],
        'shipment_status': shipment_block['shipment_status'],
        'booking_no': shipment_block['booking_no'],
        'route_summary': route_block['summary'],
        'pod_status': pod_block['status'],
        'collection_status': cod_block['collection_status'],
        'order_type': shipment_block['order_type'],
        'operational_stage': status_block['operational_stage'],
    }
