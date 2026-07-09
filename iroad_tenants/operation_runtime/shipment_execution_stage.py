"""
Shipment-bound execution sub-stages (pickup → loading → forward lifecycle).

Booking-only flows keep A2/A3 on the booking context when no active shipment exists.
Shipment-linked mobile Job Detail executes pickup/loading against the shipment row.
"""

from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantOperationActionLog, TenantShipment
from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_shipment_status_impact,
)

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
    STAGE_POD: 'Delivered',
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


def is_confirm_loaded_action(action) -> bool:
    if action is None:
        return False
    code = (getattr(action, 'action_code', '') or '').strip().upper()
    if code in {'A4', 'OA-0004'}:
        return True
    return operation_action_matches(action, 'confirm loaded', 'confirm_loaded')


def is_loading_completed_action(action) -> bool:
    if action is None or is_confirm_loaded_action(action):
        return False
    label = (getattr(action, 'english_label', '') or '').casefold()
    if 'loading completed' in label or 'load complete' in label:
        return True
    if getattr(action, 'auto_shipment_post', False):
        return True
    return operation_action_matches(action, 'loading completed')


def is_pickup_or_loading_action(action) -> bool:
    return is_pickup_action(action) or is_loading_action(action)


def is_unloading_completed_action(action) -> bool:
    if action is None:
        return False
    label = (getattr(action, 'english_label', '') or '').casefold()
    if 'unloading completed' in label or 'unload complete' in label:
        return True
    return operation_action_matches(action, 'unloading completed')


def is_unloading_action(action) -> bool:
    """Start Unloading — label-driven; tenant OA codes vary after portal edits."""
    if action is None or is_unloading_completed_action(action):
        return False
    label = (getattr(action, 'english_label', '') or '').casefold()
    if 'start unloading' in label:
        return True
    code = (getattr(action, 'action_code', '') or '').strip().upper()
    if code == 'A8':
        return True
    return operation_action_matches(action, 'a8', 'action 8')


def is_departure_action(action) -> bool:
    if action is None:
        return False
    from iroad_tenants.operation_runtime.movement_action_validator import (
        is_empty_move_catalog_action,
    )

    if is_empty_move_catalog_action(action):
        return False
    impact = resolve_shipment_status_impact(
        (getattr(action, 'shipment_status_impact', None) or '').strip(),
    )
    if impact == TenantShipment.ShipmentStatus.IN_TRANSIT:
        return True
    return operation_action_matches(
        action,
        'depart in transit',
        'departure',
        'depart',
        'a5',
        'action 5',
    )


def is_delivery_arrival_action(action) -> bool:
    if action is None or is_unloading_action(action):
        return False
    code = (getattr(action, 'action_code', '') or '').strip().upper()
    if code in {'A6', 'OA-0006'}:
        return True
    impact = resolve_shipment_status_impact(
        (getattr(action, 'shipment_status_impact', None) or '').strip(),
    )
    if impact == TenantShipment.ShipmentStatus.AT_DELIVERY:
        return True
    return operation_action_matches(
        action,
        'delivery arrival',
        'arrival at delivery',
        'action 6',
    )


def _delivery_milestones_from_log_rows(log_rows) -> tuple[bool, bool]:
    delivery_done = False
    unloading_done = False
    for log in log_rows:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        if is_unloading_action(action):
            unloading_done = True
        elif is_delivery_arrival_action(action):
            delivery_done = True
        if delivery_done and unloading_done:
            break
    return delivery_done, unloading_done


def _log_event_timestamp(log) -> Any:
    return getattr(log, 'log_date', None) or getattr(log, 'created_at', None)


def _shipment_logs_for_milestones(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
):
    if shipment is None:
        return []
    if prefetched_logs is not None:
        rows = list(prefetched_logs)
        if exclude_log_id:
            rows = [
                row
                for row in rows
                if str(getattr(row, 'log_id', None) or getattr(row, 'pk', '') or '')
                != str(exclude_log_id)
            ]
        return rows

    shipment_id = getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', None)
    if not shipment_id:
        return []
    try:
        from uuid import UUID

        UUID(str(shipment_id))
    except (TypeError, ValueError, AttributeError):
        return []
    qs = TenantOperationActionLog.objects.filter(
        shipment_id=shipment_id,
    ).select_related('operation_action').order_by('log_date', 'created_at')
    if exclude_log_id:
        qs = qs.exclude(pk=exclude_log_id)
    return list(qs)


def _pod_upload_timestamps_from_logs(
    logs,
) -> tuple[Any | None, Any | None, Any | None]:
    """Return latest POD, delivery-arrival, and unloading log timestamps."""
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    pod_ts = None
    delivery_ts = None
    unloading_ts = None
    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        ts = _log_event_timestamp(log)
        if ts is None:
            continue
        if is_pod_upload_action(action):
            pod_ts = ts if pod_ts is None or ts > pod_ts else pod_ts
        if is_delivery_arrival_action(action):
            delivery_ts = ts if delivery_ts is None or ts > delivery_ts else delivery_ts
        if is_unloading_action(action):
            unloading_ts = ts if unloading_ts is None or ts > unloading_ts else unloading_ts
    return pod_ts, delivery_ts, unloading_ts


def _pod_log_has_gps_capture(log) -> bool:
    """True when driver execute captured GPS coordinates on the Action Log."""
    if log is None:
        return False
    lat = str(getattr(log, 'latitude', '') or '').strip()
    lng = str(getattr(log, 'longitude', '') or '').strip()
    return bool(lat and lng)


def _pod_log_has_evidence_media(log) -> bool:
    """True when an Action Log row has persisted photo/video evidence."""
    if log is None:
        return False
    try:
        from tenant_workspace.models import TenantOperationActionMedia

        log_id = getattr(log, 'log_id', None) or getattr(log, 'pk', None)
        if not log_id:
            return False
        return TenantOperationActionMedia.objects.filter(action_log_id=log_id).exists()
    except Exception:
        return False


def _shipment_pod_upload_substantively_complete(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """
  Label-only POD (``auto_pod_post`` off) is complete only with media on the log.

    A bare execute log from the evidence screen must not block POD retry or mark
    the shipment POD column complete.
    """
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    logs = _shipment_logs_for_milestones(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    pod_logs = [
        log
        for log in logs
        if is_pod_upload_action(getattr(log, 'operation_action', None))
    ]
    if not pod_logs:
        return False

    latest = max(pod_logs, key=_log_event_timestamp)
    action = getattr(latest, 'operation_action', None)
    if action is not None and getattr(action, 'auto_pod_post', False):
        from mobile_api.dashboard.selectors.pod_cod_policy import derive_pod_compliant

        return derive_pod_compliant(shipment)

    if _pod_log_has_evidence_media(latest):
        return True
    if _pod_log_has_gps_capture(latest):
        return True

    try:
        from mobile_api.pod_capture.models import PodCaptureStagingBundle

        shipment_id = getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', None)
        if shipment_id and PodCaptureStagingBundle.objects.filter(
            shipment_id=shipment_id,
            status='promoted',
        ).exists():
            return True
    except Exception:
        pass

    return False


def shipment_pod_upload_log_is_valid(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """
    True when POD milestones are satisfied and capture is substantively complete.

    Label-only POD may log OA-0009 on first tap without media; log ordering alone
    must not mark upload complete while evidence is still outstanding.
    """
    delivery_done, unloading_done = _shipment_delivery_milestones_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    if not (delivery_done and unloading_done):
        return False
    pod_ts, delivery_ts, unloading_ts = _pod_upload_timestamps_from_logs(
        _shipment_logs_for_milestones(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ),
    )
    if pod_ts is None or delivery_ts is None or unloading_ts is None:
        return False
    if not (pod_ts >= delivery_ts and pod_ts >= unloading_ts):
        return False
    return _shipment_pod_upload_substantively_complete(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )


def shipment_pod_upload_execution_counts(
    shipment,
    action,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """
    A prior POD log blocks re-execute only when delivery + unloading preceded it.

    Out-of-order POD attempts (logged before arrival/unloading) do not count.
    """
    if shipment is None or action is None:
        return False
    if not getattr(action, 'auto_pod_post', False):
        return True
    delivery_done, unloading_done = _shipment_delivery_milestones_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    if not (delivery_done and unloading_done):
        return False

    action_id = str(getattr(action, 'action_id', '') or '').strip()
    pod_ts = None
    for log in _shipment_logs_for_milestones(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        row_action = getattr(log, 'operation_action', None)
        if row_action is None:
            continue
        ts = _log_event_timestamp(log)
        if ts is None:
            continue
        row_action_id = str(getattr(row_action, 'action_id', '') or '').strip()
        if action_id and row_action_id == action_id:
            pod_ts = ts if pod_ts is None or ts > pod_ts else pod_ts

    if pod_ts is None:
        return False

    _pod_ts, delivery_ts, unloading_ts = _pod_upload_timestamps_from_logs(
        _shipment_logs_for_milestones(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ),
    )
    if delivery_ts is None or unloading_ts is None:
        return False
    return pod_ts >= delivery_ts and pod_ts >= unloading_ts


def _shipment_delivery_milestones_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> tuple[bool, bool]:
    if shipment is None:
        return False, False
    if prefetched_logs is not None:
        rows = list(prefetched_logs)
        if exclude_log_id:
            rows = [
                row
                for row in rows
                if str(getattr(row, 'log_id', None) or getattr(row, 'pk', '') or '')
                != str(exclude_log_id)
            ]
        return _delivery_milestones_from_log_rows(rows)

    shipment_id = getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', None)
    if not shipment_id:
        return False, False
    try:
        from uuid import UUID

        UUID(str(shipment_id))
    except (TypeError, ValueError, AttributeError):
        return False, False
    qs = TenantOperationActionLog.objects.filter(
        shipment_id=shipment_id,
    ).select_related('operation_action').order_by('log_date', 'created_at')
    if exclude_log_id:
        qs = qs.exclude(pk=exclude_log_id)
    return _delivery_milestones_from_log_rows(qs)


def shipment_loading_completed_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """Loading Completed logged, or implied once departure / in-transit milestones exist."""
    if shipment is None:
        return False
    for log in _shipment_logs_for_milestones(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        action = getattr(log, 'operation_action', None)
        if is_loading_completed_action(action):
            return True
    if shipment_departure_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        return True
    return shipment_at_or_past_in_transit(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )


def shipment_departure_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """True when Departure / In Transit was logged on this shipment."""
    if shipment is None:
        return False
    for log in _shipment_logs_for_milestones(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        if is_departure_action(getattr(log, 'operation_action', None)):
            return True
    return False


def shipment_at_or_past_in_transit(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """
    True when the shipment is in transit or later — by column status or departure log.

    Tenant-configured Departure rows may omit shipment_status_impact, leaving the
    column on Loaded while the driver has already departed.
    """
    if shipment is None:
        return False
    current = (getattr(shipment, 'shipment_status', None) or '').strip()
    if current in {
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }:
        return True
    return shipment_departure_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )


def shipment_delivery_arrival_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """True when Delivery Arrival was logged on this shipment."""
    delivery_done, _unloading_done = _shipment_delivery_milestones_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    return delivery_done


def shipment_unloading_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """True when Start Unloading was logged on this shipment."""
    _delivery_done, unloading_done = _shipment_delivery_milestones_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    return unloading_done


def shipment_unloading_completed_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """True when Unloading Completed was logged on this shipment."""
    if shipment is None:
        return False
    for log in _shipment_logs_for_milestones(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        if is_unloading_completed_action(getattr(log, 'operation_action', None)):
            return True
    return False


def shipment_allows_unloading_completed_action(
    action,
    shipment,
    *,
    exclude_log_id=None,
) -> bool:
    """Unloading Completed requires delivery arrival and Start Unloading first."""
    if shipment is None or action is None or not is_unloading_completed_action(action):
        return False
    current = (shipment.shipment_status or '').strip()
    if current in _TERMINAL_SHIPMENT_STATUSES:
        return False
    if not shipment_delivery_arrival_done(
        shipment,
        exclude_log_id=exclude_log_id,
    ):
        return False
    if not shipment_unloading_done(
        shipment,
        exclude_log_id=exclude_log_id,
    ):
        return False
    if shipment_unloading_completed_done(
        shipment,
        exclude_log_id=exclude_log_id,
    ):
        return False
    return shipment_at_or_past_in_transit(
        shipment,
        exclude_log_id=exclude_log_id,
    )


def shipment_pod_prerequisites_done(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """POD requires delivery arrival and unloading milestones (completed preferred)."""
    delivery_done, unloading_done = _shipment_delivery_milestones_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )
    if not delivery_done:
        return False
    if unloading_done:
        return True
    return shipment_unloading_completed_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )


def shipment_ready_for_pod_capture(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> bool:
    """True only after unloading milestones — digital POD capture may open."""
    if shipment is None:
        return False
    if not shipment_pod_prerequisites_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        return False
    if not shipment_unloading_completed_done(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    ):
        return False
    return not shipment_pod_upload_log_is_valid(
        shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )


def shipment_allows_unloading_action(
    action,
    shipment,
    *,
    exclude_log_id=None,
) -> bool:
    """
    Shipment-bound Start Unloading (OA-0007).

    Requires Delivery Arrival logged first; one explicit unload log per shipment.
    """
    if shipment is None or action is None or not is_unloading_action(action):
        return False
    current = shipment.shipment_status or ''
    if current in _TERMINAL_SHIPMENT_STATUSES:
        return False
    delivery_done, unloading_done = _shipment_delivery_milestones_done(
        shipment,
        exclude_log_id=exclude_log_id,
    )
    at_delivery_site = delivery_done or current in {
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }
    if unloading_done or not at_delivery_site:
        return False
    return shipment_at_or_past_in_transit(
        shipment,
        exclude_log_id=exclude_log_id,
    )


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


def infer_shipment_status_from_milestone_log_rows(
    log_rows,
    *,
    shipment=None,
    exclude_log_id=None,
    prefetched_logs=None,
) -> str | None:
    """
    Map workflow milestone logs → shipment_status column when Action Master rows
    omit ``shipment_status_impact`` (label-only Departure / Delivery / Unload).
    """
    from iroad_tenants.operation_runtime.workflow_action_policy import (
        action_is_job_close,
    )
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    rows = list(log_rows or [])
    if shipment is not None and not rows:
        rows = list(
            _shipment_logs_for_milestones(
                shipment,
                exclude_log_id=exclude_log_id,
                prefetched_logs=prefetched_logs,
            ),
        )

    for log in rows:
        if action_is_job_close(getattr(log, 'operation_action', None)):
            return TenantShipment.ShipmentStatus.CLOSED

    if shipment is not None:
        if shipment_pod_upload_log_is_valid(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=rows or prefetched_logs,
        ):
            from iroad_tenants.operation_runtime.latest_state import (
                clamp_shipment_status_cache_for_hard_pod,
            )

            return clamp_shipment_status_cache_for_hard_pod(
                shipment,
                TenantShipment.ShipmentStatus.POD_SUBMITTED,
            )
    elif any(
        is_pod_upload_action(getattr(log, 'operation_action', None)) for log in rows
    ):
        return TenantShipment.ShipmentStatus.POD_SUBMITTED

    delivery_done, unloading_done = _delivery_milestones_from_log_rows(rows)
    unloading_completed = any(
        is_unloading_completed_action(getattr(log, 'operation_action', None))
        for log in rows
    )
    if unloading_completed or unloading_done or delivery_done:
        if (
            shipment is not None
            and unloading_completed
            and (shipment.order_type or '').strip().upper() != 'COD'
        ):
            return TenantShipment.ShipmentStatus.DELIVERED
        return TenantShipment.ShipmentStatus.AT_DELIVERY

    if any(
        is_departure_action(getattr(log, 'operation_action', None)) for log in rows
    ):
        return TenantShipment.ShipmentStatus.IN_TRANSIT

    if shipment is not None:
        _pickup_done, loading_done = _shipment_pickup_loading_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=rows or prefetched_logs,
        )
    else:
        loading_done = any(
            is_loading_action(getattr(log, 'operation_action', None))
            or is_loading_completed_action(getattr(log, 'operation_action', None))
            or is_confirm_loaded_action(getattr(log, 'operation_action', None))
            for log in rows
        )
    if loading_done:
        return TenantShipment.ShipmentStatus.LOADED

    return None


def infer_shipment_status_from_milestone_logs(
    shipment,
    *,
    exclude_log_id=None,
    prefetched_logs=None,
) -> str | None:
    """Shipment column status implied by driver workflow logs (no impact flags)."""
    if shipment is None:
        return None
    return infer_shipment_status_from_milestone_log_rows(
        [],
        shipment=shipment,
        exclude_log_id=exclude_log_id,
        prefetched_logs=prefetched_logs,
    )


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
    if current == TenantShipment.ShipmentStatus.CLOSED:
        return STAGE_COMPLETION
    if current == TenantShipment.ShipmentStatus.DELIVERED:
        if shipment_pod_prerequisites_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ) and not shipment_pod_upload_log_is_valid(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ):
            return STAGE_POD
        if (shipment.order_type or '').upper() == 'COD' and (
            shipment.collection_status
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            return STAGE_COD
        return STAGE_COMPLETION

    if current == TenantShipment.ShipmentStatus.IN_TRANSIT:
        return STAGE_IN_TRANSIT

    if current == TenantShipment.ShipmentStatus.AT_DELIVERY:
        if shipment_pod_prerequisites_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ) and not shipment_pod_upload_log_is_valid(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ):
            return STAGE_POD
        if (shipment.order_type or '').upper() == 'COD' and (
            shipment.collection_status
            != TenantShipment.CollectionStatus.COLLECTED
        ) and shipment_unloading_completed_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ) and shipment_pod_upload_log_is_valid(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ):
            return STAGE_COD
        return STAGE_DELIVERY

    if current == TenantShipment.ShipmentStatus.POD_SUBMITTED:
        if (shipment.order_type or '').upper() == 'COD' and (
            shipment.collection_status
            != TenantShipment.CollectionStatus.COLLECTED
        ):
            from iroad_tenants.operation_runtime.side_effects import (
                _mobile_pod_compliance_satisfied,
            )

            if _mobile_pod_compliance_satisfied(shipment):
                return STAGE_COD
        return STAGE_POD

    if current in _EARLY_SHIPMENT_STATUSES:
        pickup_done, loading_done = _shipment_pickup_loading_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        )
        if loading_done and shipment_departure_done(
            shipment,
            exclude_log_id=exclude_log_id,
            prefetched_logs=prefetched_logs,
        ):
            if shipment_pod_prerequisites_done(
                shipment,
                exclude_log_id=exclude_log_id,
                prefetched_logs=prefetched_logs,
            ):
                return STAGE_POD
            delivery_done, _unloading_done = _shipment_delivery_milestones_done(
                shipment,
                exclude_log_id=exclude_log_id,
                prefetched_logs=prefetched_logs,
            )
            if delivery_done:
                return STAGE_DELIVERY
            return STAGE_IN_TRANSIT
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
