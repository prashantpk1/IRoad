"""Canonical mobile job pointer (dashboard + job detail)."""
from __future__ import annotations

from typing import Any


def build_open_job_pointer(
    *,
    job_type: str,
    job_id: str,
    job_no: str = '',
    booking_item_type: str = '',
    backload_bootstrap_pending: bool = False,
) -> dict[str, Any]:
    """Explicit target for Open Job / navigation resume."""
    jt = (job_type or '').strip()
    jid = (job_id or '').strip()
    if not jt or not jid:
        return {}
    pointer: dict[str, Any] = {
        'job_type': jt,
        'job_id': jid,
        'job_no': str(job_no or ''),
        'booking_item_type': str(booking_item_type or ''),
    }
    if backload_bootstrap_pending:
        pointer['backload_bootstrap_pending'] = True
    return pointer


def attach_open_job_pointer(payload: dict[str, Any]) -> None:
    """Attach ``open_job`` from dashboard/job header fields on ``payload``."""
    pointer = build_open_job_pointer(
        job_type=str(payload.get('job_type') or ''),
        job_id=str(payload.get('job_id') or ''),
        job_no=str(payload.get('job_no') or ''),
        booking_item_type=str(payload.get('booking_item_type') or ''),
        backload_bootstrap_pending=bool(payload.get('backload_bootstrap_pending')),
    )
    if pointer:
        payload['open_job'] = pointer


def build_job_navigation_block(
    *,
    job_type: str,
    job_id: str,
    resolver_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tell mobile to replace stale shipment routes (back button / resume)."""
    jt = (job_type or '').strip()
    jid = (job_id or '').strip()
    if not jt or not jid:
        return {}

    meta = dict(resolver_meta or {})
    navigation: dict[str, Any] = {
        'canonical_job_type': jt,
        'canonical_job_id': jid,
    }
    if meta.get('backload_booking_redirect'):
        navigation['replace_stack'] = True
        navigation['redirect_reason'] = 'backload_bootstrap'
        redirected = str(meta.get('redirected_from_shipment_id') or '').strip()
        if redirected:
            navigation['redirected_from_shipment_id'] = redirected
    elif meta.get('closed_shipment_active_leg_redirect'):
        navigation['replace_stack'] = True
        navigation['redirect_reason'] = 'active_leg'
        redirected = str(meta.get('redirected_from_shipment_id') or '').strip()
        if redirected:
            navigation['redirected_from_shipment_id'] = redirected
    elif meta.get('active_shipment_redirect'):
        navigation['replace_stack'] = True
        navigation['redirect_reason'] = 'active_shipment'
    return navigation
