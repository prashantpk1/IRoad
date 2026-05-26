"""
mobile_api/dashboard/services/dashboard_etag_service.py

Deterministic dashboard content hash and ETag generation for polling.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.selectors import pod_cod_policy


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)


def _entity_id(value: Any) -> str:
    if value is None:
        return ''
    return str(getattr(value, 'pk', None) or getattr(value, 'booking_id', None) or getattr(value, 'shipment_id', None) or getattr(value, 'movement_id', None) or value or '')


def pod_cod_fingerprint_tuple(pod: dict[str, Any] | None) -> tuple:
    """Stable POD/COD booleans for hashing."""
    p = pod or {}
    return (
        bool(p.get('pod_pending')),
        bool(p.get('pod_compliant')),
        bool(p.get('hard_pod_pending')),
        bool(p.get('cod_pending')),
        bool(p.get('cod_collected')),
        bool(p.get('treasury_pending')),
        bool(p.get('delivery_blocked')),
    )


def _reconciliation_versions(context: DriverDashboardContext) -> dict[str, str]:
    recon = context.reconciliation or {}
    return {
        'reconciliation_version': (recon.get('reconciliation_version') or '').strip(),
        'workflow_projection_version': (
            recon.get('workflow_projection_version') or ''
        ).strip(),
        'compliance_projection_version': (
            recon.get('compliance_projection_version') or ''
        ).strip(),
    }


def build_invalidation_fingerprint(
    context: DriverDashboardContext,
    *,
    latest_action_log_id: str = '',
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pre-workflow fingerprint — invalidates cache when selection, logs, or compliance move.

    Uses authoritative statuses from reconciliation when present (not raw columns only).
    """
    from mobile_api.dashboard.services.dashboard_status_reconciler import (
        authoritative_movement_status,
        authoritative_shipment_status,
    )

    shipment = context.active_shipment
    movement = context.active_empty_movement

    if pod_cod is None and shipment is not None:
        pod_cod = pod_cod_policy.derive_pod_cod_flags(
            shipment,
            driver=context.driver,
        )

    ship_auth = authoritative_shipment_status(context)
    mov_auth = authoritative_movement_status(context)

    return {
        'tenant_schema': (context.tenant_schema or '').strip(),
        'user_id': (context.user_id or '').strip(),
        'booking_id': _entity_id(context.active_booking),
        'active_shipment_id': _entity_id(shipment),
        'movement_id': _entity_id(movement),
        'shipment_status': ship_auth
        or str(getattr(shipment, 'shipment_status', '') or '').strip(),
        'movement_status': mov_auth
        or str(getattr(movement, 'status', '') or '').strip(),
        'latest_action_log_id': (latest_action_log_id or '').strip(),
        'pod_cod': pod_cod_fingerprint_tuple(pod_cod),
        'booking_execution_stage': (
            (context.booking_selection.booking_execution_stage or '')
            if context.booking_selection
            else ''
        ),
        **_reconciliation_versions(context),
    }


def build_content_fingerprint(
    context: DriverDashboardContext,
    *,
    latest_action_log_id: str = '',
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Full dashboard content hash inputs (includes workflow allowed-action count).
    """
    fp = build_invalidation_fingerprint(
        context,
        latest_action_log_id=latest_action_log_id,
        pod_cod=pod_cod,
    )
    workflow = context.workflow_projection or {}
    next_action = workflow.get('next_action') or {}
    primary_action = workflow.get('primary_action') or {}
    fp['allowed_action_count'] = len(workflow.get('allowed_actions') or [])
    fp['workflow_stage'] = (workflow.get('current_stage') or '').strip()
    fp['next_action_code'] = str(
        next_action.get('action_code') or primary_action.get('action_code') or ''
    ).strip()
    fp['allowed_action_codes'] = sorted(
        str(item.get('action_code') or '').strip()
        for item in (workflow.get('allowed_actions') or [])
        if isinstance(item, dict) and (item.get('action_code') or '').strip()
    )
    fp['drift_detected'] = bool((context.reconciliation or {}).get('any_drift'))
    fp.update(_reconciliation_versions(context))
    wi = (context.reconciliation or {}).get('workflow_integrity') or {}
    fp['workflow_integrity_state'] = (wi.get('workflow_integrity_state') or '').strip()
    return fp


def fingerprint_digest(fingerprint: dict[str, Any]) -> str:
    """SHA-256 hex digest of a fingerprint dict."""
    payload = _stable_json(fingerprint)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def build_etag_from_fingerprint(fingerprint: dict[str, Any]) -> str:
    """Strong ETag value for ``If-None-Match`` / response ``ETag`` header."""
    return f'"{fingerprint_digest(fingerprint)}"'


def etag_matches_request(request: Any, etag: str) -> bool:
    """True when client ``If-None-Match`` equals this ETag (strong comparison)."""
    if not etag or request is None:
        return False
    client = (request.META.get('HTTP_IF_NONE_MATCH') or '').strip()
    if not client:
        return False
    if client == etag:
        return True
    # Allow weak validators listing multiple etags.
    tag = etag.strip('"')
    for part in client.split(','):
        part = part.strip()
        if part.startswith('W/'):
            part = part[2:].strip()
        if part.strip('"') == tag:
            return True
    return False
