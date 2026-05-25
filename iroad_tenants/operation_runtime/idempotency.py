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
