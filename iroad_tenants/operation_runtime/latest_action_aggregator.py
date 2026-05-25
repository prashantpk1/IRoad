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
from tenant_workspace.models import TenantOperationActionLog, TenantTruckMovementLog

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
    qs = (
        TenantOperationActionLog.objects.filter(
            Q(shipment_id=shipment.pk)
            | Q(truck_movement__shipment_id=shipment.pk),
        )
        .exclude(operation_action__isnull=True)
        .select_related('operation_action', 'driver')
        .order_by('-log_date', '-created_at', '-log_id')
    )
    if movement is not None:
        qs = qs.filter(
            Q(shipment_id=shipment.pk) | Q(truck_movement_id=movement.pk),
        )
    if driver_id:
        qs = qs.filter(driver_id=driver_id)
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
        qs = qs.filter(driver_id=driver_id)
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
    return resolve_shipment_status_impact(
        (action.shipment_status_impact or '').strip(),
    )


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
