"""Action log idempotency and duplicate-submit guards."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from tenant_workspace.models import TenantOperationActionLog


def normalize_idempotency_key(raw_value: str) -> str:
    token = (raw_value or '').strip()
    if not token:
        return ''
    return token[:128]


def normalize_source_ref(raw_value: str) -> str:
    token = (raw_value or '').strip()
    if not token:
        return ''
    return token[:128]


def idempotent_log_matches_job_scope(
    *,
    log,
    job_type: str = '',
    movement=None,
    shipment=None,
    booking=None,
) -> bool:
    """
    Idempotency replay is valid only when the existing log belongs to the same job.
    """
    if log is None:
        return False

    job = (job_type or '').strip().casefold()
    if job == 'movement' and movement is not None:
        log_movement_id = getattr(log, 'truck_movement_id', None)
        current_id = getattr(movement, 'pk', None)
        if log_movement_id is None or current_id is None:
            return False
        return str(log_movement_id) == str(current_id)

    if job == 'shipment' and shipment is not None:
        log_shipment_id = getattr(log, 'shipment_id', None)
        current_id = getattr(shipment, 'pk', None)
        if log_shipment_id is None or current_id is None:
            return False
        return str(log_shipment_id) == str(current_id)

    if job == 'booking' and booking is not None:
        log_booking_id = getattr(log, 'booking_id', None)
        current_id = getattr(booking, 'pk', None)
        if log_booking_id is None or current_id is None:
            return True
        return str(log_booking_id) == str(current_id)

    return True


def find_recent_duplicate(
    *,
    shipment=None,
    movement=None,
    operation_action=None,
    created_by_label: str = '',
    notes: str = '',
    source: str = 'Manual',
    minutes: int = 2,
):
    if operation_action is None:
        return None
    threshold = timezone.now() - timedelta(minutes=minutes)
    qs = (
        TenantOperationActionLog.objects.filter(
            operation_action=operation_action,
            source=(source or 'Manual')[:32],
            notes=(notes or ''),
            created_by_label=(created_by_label or '')[:200],
            created_at__gte=threshold,
        )
        .order_by('-created_at')
    )
    if shipment is not None:
        qs = qs.filter(shipment=shipment)
    elif movement is not None:
        qs = qs.filter(truck_movement_id=movement.pk)
    return qs.first()
