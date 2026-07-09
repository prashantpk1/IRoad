"""Recover stuck Hard POD custody rows (submitted but never promoted)."""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

from mobile_api.hard_pod.models import HardPODCustodySubmission

_hard_pod_promotion_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    'hard_pod_promotion_active',
    default=False,
)


def is_hard_pod_promotion_active() -> bool:
    return bool(_hard_pod_promotion_active.get())


@contextmanager
def hard_pod_promotion_guard() -> Iterator[None]:
    """Prevent recovery/execute loops while hard POD custody is being promoted."""
    token = _hard_pod_promotion_active.set(True)
    try:
        yield
    finally:
        _hard_pod_promotion_active.reset(token)


def try_recover_unpromoted_hard_pod_custody(
    *,
    driver: Any | None,
    shipment: Any | None,
    tenant_schema: str = '',
) -> bool:
    """
    Promote verified custody when mobile submitted checklist but execute never ran.

    Safe to call on Job Detail refresh — idempotent via execute client_action_id.
    Must not run while Execute Action is building projections (recursion guard).
    """
    if is_hard_pod_promotion_active():
        return False
    if driver is None or shipment is None:
        return False
    schema = (tenant_schema or '').strip()
    shipment_id = str(
        getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', '') or ''
    ).strip()
    driver_id = str(
        getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or ''
    ).strip()
    if not (schema and shipment_id and driver_id):
        return False

    submission = (
        HardPODCustodySubmission.objects.filter(
            tenant_schema=schema,
            shipment_id=shipment_id,
            driver_id=driver_id,
            promoted_at__isnull=True,
        )
        .order_by('-submitted_at', '-created_at')
        .first()
    )
    if submission is None:
        return False

    from mobile_api.hard_pod.models import HardPODCustodySubmissionEvent

    if not HardPODCustodySubmissionEvent.objects.filter(
        submission=submission,
        event_type=HardPODCustodySubmissionEvent.EventType.VERIFIED,
    ).exists():
        return False

    from mobile_api.hard_pod.services.hard_pod_submit_service import HardPodSubmitService

    payload = {
        'latitude': submission.latitude,
        'longitude': submission.longitude,
        'handoff_notes': submission.handoff_notes,
    }
    with hard_pod_promotion_guard():
        result = HardPodSubmitService()._promote_custody_via_execute(
            submission=submission,
            driver=driver,
            shipment=shipment,
            tenant_schema=schema,
            payload=payload,
        )
    return bool(result and result.get('promoted'))
