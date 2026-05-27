"""
Shipment-bound execution sub-stages (pickup → loading → forward lifecycle).

Booking-only flows keep A2/A3 on the booking context when no active shipment exists.
Shipment-linked mobile Job Detail executes pickup/loading against the shipment row.
"""

from __future__ import annotations

from tenant_workspace.models import TenantOperationActionLog, TenantShipment
from iroad_tenants.operation_runtime.impacts import operation_action_matches

# Sub-stages before / beside shipment_status column values.
STAGE_PICKUP = 'pickup'
STAGE_LOADING = 'loading'
STAGE_PRE_TRANSIT = 'pre_transit'
STAGE_IN_TRANSIT = 'in_transit'
STAGE_DELIVERY = 'delivery'
STAGE_POD = 'pod'
STAGE_COD = 'cod'
STAGE_COMPLETION = 'completion'
STAGE_CANCELLED = 'cancelled'

_EARLY_SHIPMENT_STATUSES = {
    TenantShipment.ShipmentStatus.CREATED,
    TenantShipment.ShipmentStatus.LOADED,
}

_TERMINAL_SHIPMENT_STATUSES = {
    TenantShipment.ShipmentStatus.CLOSED,
    TenantShipment.ShipmentStatus.CANCELLED,
}

_STATUS_TO_EXECUTION_STAGE = {
    TenantShipment.ShipmentStatus.IN_TRANSIT: STAGE_IN_TRANSIT,
    TenantShipment.ShipmentStatus.AT_DELIVERY: STAGE_DELIVERY,
    TenantShipment.ShipmentStatus.POD_SUBMITTED: STAGE_POD,
    TenantShipment.ShipmentStatus.DELIVERED: STAGE_COMPLETION,
    TenantShipment.ShipmentStatus.CLOSED: STAGE_COMPLETION,
    TenantShipment.ShipmentStatus.CANCELLED: STAGE_CANCELLED,
}

# Human labels for mobile reporting (not policy).
_STAGE_LABELS = {
    STAGE_PICKUP: 'Pickup',
    STAGE_LOADING: 'Loading',
    STAGE_PRE_TRANSIT: 'Loaded',
    STAGE_IN_TRANSIT: 'In Transit',
    STAGE_DELIVERY: 'Delivery',
    STAGE_POD: 'POD',
    STAGE_COD: 'COD',
    STAGE_COMPLETION: 'Completed',
    STAGE_CANCELLED: 'Cancelled',
}


def is_pickup_action(action) -> bool:
    return operation_action_matches(
        action,
        'pickup',
        'a2',
        'action 2',
        'arrival at pickup',
        'pickup arrival',
    )


def is_loading_action(action) -> bool:
    return operation_action_matches(action, 'start loading', 'a3', 'action 3')


def is_pickup_or_loading_action(action) -> bool:
    return is_pickup_action(action) or is_loading_action(action)


def _pickup_loading_from_log_rows(
    log_rows,
    *,
    exclude_log_id=None,
) -> tuple[bool, bool]:
    pickup_done = False
    loading_done = False
    for log in log_rows or []:
        if exclude_log_id and str(getattr(log, 'log_id', '')) == str(exclude_log_id):
            continue
        act = getattr(log, 'operation_action', None)
        if is_pickup_action(act):
            pickup_done = True
        if is_loading_action(act):
            loading_done = True
        if pickup_done and loading_done:
            break
    return pickup_done, loading_done


def _shipment_pickup_loading_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> tuple[bool, bool]:
    """Whether pickup (A2) and loading (A3) were logged on this shipment."""
    if shipment is None:
        return False, False
    if prefetched_logs is not None:
        return _pickup_loading_from_log_rows(
            prefetched_logs,
            exclude_log_id=exclude_log_id,
        )
    qs = TenantOperationActionLog.objects.filter(
        shipment_id=shipment.pk,
    ).exclude(operation_action__isnull=True)
    if shipment.booking_id:
        qs = (
            qs
            | TenantOperationActionLog.objects.filter(
                booking_id=shipment.booking_id,
                shipment__isnull=True,
            ).exclude(operation_action__isnull=True)
        )
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    pickup_done = False
    loading_done = False
    for log in qs.select_related('operation_action').order_by('-log_date', '-created_at')[:200]:
        act = log.operation_action
        if is_pickup_action(act):
            pickup_done = True
        if is_loading_action(act):
            loading_done = True
        if pickup_done and loading_done:
            break
    return pickup_done, loading_done


def derive_shipment_execution_stage(
    shipment,
    *,
    status_for_stage: str | None = None,
    exclude_log_id=None,
    prefetched_logs=None,
) -> str:
    """
    Derive execution sub-stage from shipment_status + shipment-bound action logs.

    Early lifecycle (Created/Loaded) uses log sequencing for pickup → loading.
    Later phases map from shipment_status (In Transit → Delivery → POD → …).
    """
    if shipment is None:
        return ''

    current = (status_for_stage or shipment.shipment_status or '').strip()
    if current == TenantShipment.ShipmentStatus.CANCELLED:
        return STAGE_CANCELLED
    if current in (
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.DELIVERED,
    ):
        return STAGE_COMPLETION

    if current == TenantShipment.ShipmentStatus.POD_SUBMITTED:
        return STAGE_POD

    if current == TenantShipment.ShipmentStatus.AT_DELIVERY:
        if (shipment.order_type or '').upper() == 'COD' and (
            shipment.collection_status
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return STAGE_COD
        return STAGE_DELIVERY

    if current == TenantShipment.ShipmentStatus.IN_TRANSIT:
        if (shipment.order_type or '').upper() == 'COD' and (
            shipment.collection_status
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return STAGE_COD
        return STAGE_IN_TRANSIT

    if current in _EARLY_SHIPMENT_STATUSES:
        pickup_done, loading_done = _shipment_pickup_loading_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        )
        if loading_done:
            return STAGE_PRE_TRANSIT
        if not pickup_done:
            return STAGE_PICKUP
        return STAGE_PRE_TRANSIT

    mapped = _STATUS_TO_EXECUTION_STAGE.get(current)
    return mapped or current or ''


def execution_stage_operational_label(stage: str) -> str:
    """Display label for allowed-actions / job detail reporting."""
    if not stage:
        return ''
    return _STAGE_LABELS.get(stage, stage.replace('_', ' ').title())


def shipment_allows_pickup_loading_action(
    action,
    shipment,
    *,
    exclude_log_id=None,
) -> bool:
    """
    Shipment-bound pickup (A2) / loading (A3) progression.

    - A2: allowed in Created/Loaded when pickup not yet logged on shipment.
    - A3: allowed after pickup logged, before loading logged.
    - Not allowed once shipment has left early lifecycle statuses.
    """
    if shipment is None or action is None:
        return False

    current = shipment.shipment_status or ''
    if current in _TERMINAL_SHIPMENT_STATUSES:
        return False
    if current not in _EARLY_SHIPMENT_STATUSES:
        return False

    pickup_done, loading_done = _shipment_pickup_loading_done(
        shipment,
        exclude_log_id=exclude_log_id,
    )

    if is_pickup_action(action):
        return not pickup_done
    if is_loading_action(action):
        return pickup_done and not loading_done
    return False
