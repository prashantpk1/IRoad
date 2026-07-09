"""
Aggregate operation action logs into authoritative shipment/movement snapshots.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_movement_status_impact,
    resolve_shipment_status_impact,
)
from tenant_workspace.models import TenantOperationActionLog, TenantShipment, TenantTruckMovementLog

# Align with operation_execution forward rank.
SHIPMENT_STATUS_RANK = {
    'Created': 10,
    'Loaded': 20,
    'In Transit': 30,
    'At Delivery': 40,
    'POD Submitted': 50,
    'Delivered': 60,
    'Closed': 70,
    'Cancelled': 99,
}

MOVEMENT_STATUS_RANK = {
    'Scheduled': 10,
    'In Progress': 20,
    'Completed': 70,
    'Cancelled': 99,
}


def shipment_status_rank(status: str | None) -> int:
    return SHIPMENT_STATUS_RANK.get((status or '').strip(), 0)


def movement_status_rank(status: str | None) -> int:
    return MOVEMENT_STATUS_RANK.get((status or '').strip(), 0)


def _status_for_rank(rank: int) -> str | None:
    for status, value in SHIPMENT_STATUS_RANK.items():
        if value == rank:
            return status
    return None


def _clamp_authoritative_for_delivery_prerequisites(
    logs,
    authoritative: str | None,
) -> str | None:
    """
    Log-derived status must not skip delivery arrival / unloading milestones.

    Out-of-order POD logs must not block drivers from seeing delivery-phase actions.
    """
    if not authoritative:
        return authoritative
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        _delivery_milestones_from_log_rows,
        is_delivery_arrival_action,
        is_unloading_action,
    )
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    delivery_done, unloading_done = _delivery_milestones_from_log_rows(logs or [])
    pod_ts = None
    delivery_ts = None
    unloading_ts = None
    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        ts = getattr(log, 'log_date', None) or getattr(log, 'created_at', None)
        if ts is None:
            continue
        if is_pod_upload_action(action):
            pod_ts = ts if pod_ts is None or ts > pod_ts else pod_ts
        if is_delivery_arrival_action(action):
            delivery_ts = ts if delivery_ts is None or ts > delivery_ts else delivery_ts
        if is_unloading_action(action):
            unloading_ts = ts if unloading_ts is None or ts > unloading_ts else unloading_ts

    pod_valid = pod_ts is None or (
        delivery_ts is not None
        and unloading_ts is not None
        and pod_ts >= delivery_ts
        and pod_ts >= unloading_ts
    )

    cap_rank = shipment_status_rank(authoritative)
    if not delivery_done:
        cap_rank = min(cap_rank, shipment_status_rank('In Transit'))
    elif not unloading_done:
        cap_rank = min(cap_rank, shipment_status_rank('At Delivery'))
    elif not pod_valid:
        cap_rank = min(cap_rank, shipment_status_rank('At Delivery'))

    if shipment_status_rank(authoritative) <= cap_rank:
        return authoritative
    return _status_for_rank(cap_rank) or authoritative


def scoped_shipment_action_logs(
    shipment,
    *,
    movement=None,
    driver_id=None,
    exclude_log_id=None,
    scan_limit: int = 200,
):
    if shipment is None:
        return TenantOperationActionLog.objects.none()
    booking_id = getattr(shipment, 'booking_id', None)
    scope = Q(shipment_id=shipment.pk) | Q(truck_movement__shipment_id=shipment.pk)
    if booking_id:
        from tenant_workspace.models import TenantBooking

        from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
            booking_preshipment_logs_queryset,
        )

        booking = getattr(shipment, 'booking', None)
        if booking is None:
            booking = TenantBooking.objects.filter(pk=booking_id).first()
        if booking is not None:
            line = (getattr(shipment, 'booking_item_type', None) or '').strip()
            cycle_log_ids = booking_preshipment_logs_queryset(
                booking,
                booking_item_type=line,
            ).values_list('log_id', flat=True)
            scope |= Q(
                booking_id=booking_id,
                shipment__isnull=True,
                log_id__in=cycle_log_ids,
            )
        else:
            scope |= Q(booking_id=booking_id, shipment__isnull=True)
    qs = (
        TenantOperationActionLog.objects.filter(scope)
        .exclude(operation_action__isnull=True)
        .select_related('operation_action', 'driver')
        .order_by('-log_date', '-created_at', '-log_id')
    )
    if movement is not None:
        qs = qs.filter(
            Q(shipment_id=shipment.pk) | Q(truck_movement_id=movement.pk),
        )
    if driver_id:
        qs = qs.filter(
            Q(driver_id=driver_id) | Q(driver_id__isnull=True),
        )
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    return qs[:scan_limit]


def scoped_booking_action_logs(
    booking,
    *,
    driver_id=None,
    exclude_log_id=None,
    scan_limit: int = 200,
):
    """Action logs for booking-only mobile jobs (before shipment birth at A4)."""
    if booking is None:
        return TenantOperationActionLog.objects.none()
    qs = (
        TenantOperationActionLog.objects.filter(booking_id=booking.pk)
        .filter(shipment__isnull=True)
        .exclude(operation_action__isnull=True)
        .select_related('operation_action', 'driver')
        .order_by('-log_date', '-created_at', '-log_id')
    )
    if driver_id:
        qs = qs.filter(Q(driver_id=driver_id) | Q(driver_id__isnull=True))
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    return qs[:scan_limit]


def scoped_movement_action_logs(
    movement,
    *,
    driver_id=None,
    exclude_log_id=None,
    scan_limit: int = 200,
):
    if movement is None:
        return TenantOperationActionLog.objects.none()
    qs = (
        TenantOperationActionLog.objects.filter(
            truck_movement_id=movement.pk,
        )
        .exclude(operation_action__isnull=True)
        .select_related('operation_action', 'driver')
        .order_by('-log_date', '-created_at', '-log_id')
    )
    if driver_id:
        qs = qs.filter(Q(driver_id=driver_id) | Q(driver_id__isnull=True))
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    return qs[:scan_limit]


def _is_reversal_action(action) -> bool:
    return operation_action_matches(
        action,
        'reversal',
        'reject pod',
        'reject',
        'r1',
        'r2',
        'r3',
        'r4',
        'cancel shipment',
        'undo',
    )


def _impact_from_log(log_row, *, kind: str) -> str | None:
    action = getattr(log_row, 'operation_action', None)
    if action is None:
        return None
    if kind == 'movement':
        return resolve_movement_status_impact(
            (action.movement_status_impact or '').strip(),
        )
    from iroad_tenants.operation_runtime.latest_state import (
        clamp_shipment_status_cache_for_hard_pod,
        resolve_effective_shipment_status_for_action,
    )

    shipment = getattr(log_row, 'shipment', None)
    effective = resolve_effective_shipment_status_for_action(
        action=action,
        shipment=shipment,
    )
    if effective:
        return clamp_shipment_status_cache_for_hard_pod(shipment, effective)
    raw = resolve_shipment_status_impact(
        (action.shipment_status_impact or '').strip(),
    )
    if not raw:
        return None
    if (
        raw == TenantShipment.ShipmentStatus.DELIVERED
        and getattr(action, 'auto_pod_post', False)
    ):
        raw = TenantShipment.ShipmentStatus.POD_SUBMITTED
    return clamp_shipment_status_cache_for_hard_pod(shipment, raw)


def aggregate_latest_action_log(
    logs,
    *,
    request=None,
) -> dict[str, Any] | None:
    """Newest log summary (no extra query)."""
    if not logs:
        return None
    log = logs[0] if hasattr(logs, '__getitem__') else next(iter(logs), None)
    if log is None:
        return None

    action = getattr(log, 'operation_action', None)
    label = ''
    code = None
    if action is not None:
        code = action.action_code
        label = action.english_label or code or ''
        if request is not None:
            try:
                from mobile_api.helpers.i18n import get_localized_value

                label = get_localized_value(
                    request,
                    action.english_label or code or '',
                    action.arabic_label or '',
                )
            except Exception:
                pass

    return {
        'log_id': str(log.log_id),
        'log_no': log.log_no,
        'log_date': log.log_date.isoformat() if log.log_date else None,
        'action_code': code,
        'action_label': label or None,
        'source': log.source or '',
        'source_channel': log.source_channel or '',
        'shipment_status_impact': (
            (action.shipment_status_impact or '').strip() if action else ''
        ) or None,
        'movement_status_impact': (
            (action.movement_status_impact or '').strip() if action else ''
        ) or None,
    }


def derive_shipment_status_from_logs(logs) -> dict[str, Any]:
    """
    Authoritative shipment status evidence from append-only logs.

    - ``latest_impact_status``: newest log with shipment_status_impact
    - ``peak_impact_status``: highest forward rank among non-reversal impacts
    - ``authoritative_status``: peak when rank >= latest, else latest
    """
    latest_impact = None
    latest_rank = -1
    peak_impact = None
    peak_rank = -1
    log_count = 0
    reversal_count = 0

    for log in logs:
        log_count += 1
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        if _is_reversal_action(action):
            reversal_count += 1
            continue
        impact = _impact_from_log(log, kind='shipment')
        if not impact:
            continue
        rank = shipment_status_rank(impact)
        if latest_impact is None:
            latest_impact = impact
            latest_rank = rank
        if rank >= peak_rank:
            peak_impact = impact
            peak_rank = rank

    authoritative = peak_impact or latest_impact
    if latest_impact and peak_impact and peak_rank >= latest_rank:
        authoritative = peak_impact
    elif latest_impact:
        authoritative = latest_impact

    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        infer_shipment_status_from_milestone_log_rows,
    )

    shipment = None
    for log in logs or []:
        candidate = getattr(log, 'shipment', None)
        if candidate is not None:
            shipment = candidate
            break

    milestone_status = infer_shipment_status_from_milestone_log_rows(
        logs,
        shipment=shipment,
    )
    if milestone_status and (
        not authoritative
        or shipment_status_rank(milestone_status) > shipment_status_rank(authoritative)
    ):
        authoritative = milestone_status

    authoritative = _clamp_authoritative_for_delivery_prerequisites(logs, authoritative)
    from iroad_tenants.operation_runtime.latest_state import (
        clamp_shipment_status_cache_for_hard_pod,
    )

    authoritative = clamp_shipment_status_cache_for_hard_pod(shipment, authoritative)

    return {
        'latest_impact_status': latest_impact,
        'peak_impact_status': peak_impact,
        'authoritative_status': authoritative,
        'log_count': log_count,
        'reversal_log_count': reversal_count,
    }


def derive_movement_status_from_logs(logs) -> dict[str, Any]:
    latest_impact = None
    peak_impact = None
    peak_rank = -1
    log_count = 0

    for log in logs:
        log_count += 1
        impact = _impact_from_log(log, kind='movement')
        if not impact:
            continue
        rank = movement_status_rank(impact)
        if rank >= peak_rank:
            peak_impact = impact
            peak_rank = rank

    for log in logs:
        impact = _impact_from_log(log, kind='movement')
        if impact:
            latest_impact = impact
            break

    authoritative = peak_impact or latest_impact
    return {
        'latest_impact_status': latest_impact,
        'peak_impact_status': peak_impact,
        'authoritative_status': authoritative,
        'log_count': log_count,
    }
