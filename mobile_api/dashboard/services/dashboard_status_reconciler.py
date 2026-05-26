"""
mobile_api/dashboard/services/dashboard_status_reconciler.py

Read-only status reconciliation for the Unified Driver Dashboard.

Action Logs are **primary** workflow authority; mutable ORM columns are
**fallback only** with explicit integrity metadata (no silent ignore, no writes).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.dashboard.services.dashboard_etag_service import fingerprint_digest
from mobile_api.dashboard.services.dashboard_projection_cache import (
    DashboardProjectionCache,
    get_projection_cache,
)

from iroad_tenants.operation_runtime.workflow_state_reconciler import (
    reconcile_movement_execution_state,
    reconcile_shipment_execution_state,
)

# API contract values
AUTHORITY_ACTION_LOGS = 'action_logs'
AUTHORITY_COLUMNS_FALLBACK = 'columns_fallback'
AUTHORITY_HYBRID = 'action_logs_with_column_fallback'

CONFIDENCE_HIGH = 'high'
CONFIDENCE_MEDIUM = 'medium'
CONFIDENCE_LOW = 'low'

INTEGRITY_ALIGNED = 'aligned'
INTEGRITY_DRIFT = 'drift_detected'
INTEGRITY_MISSING_LOGS = 'missing_action_logs'
INTEGRITY_SPARSE_LOGS = 'sparse_action_logs'


def build_workflow_integrity(
    *,
    log_count: int,
    authoritative_status: str,
    column_status: str,
    drift_detected: bool,
    status_source: str,
) -> dict[str, Any]:
    """
    ``workflow_integrity`` block for API / sync metadata.

    Never hides missing or sparse logs — surfaces explicit warnings.
    """
    missing = log_count <= 0
    sparse = 0 < log_count < 2
    fallback = status_source in {
        AUTHORITY_COLUMNS_FALLBACK,
        'column',
        'columns_with_shipment_reconciliation',
    } or (missing and bool(column_status))

    if missing:
        authority_source = AUTHORITY_COLUMNS_FALLBACK
        confidence = CONFIDENCE_LOW
        integrity_state = INTEGRITY_MISSING_LOGS
    elif drift_detected:
        authority_source = (
            AUTHORITY_ACTION_LOGS if log_count else AUTHORITY_COLUMNS_FALLBACK
        )
        confidence = CONFIDENCE_MEDIUM if log_count else CONFIDENCE_LOW
        integrity_state = INTEGRITY_DRIFT
    elif sparse:
        authority_source = AUTHORITY_ACTION_LOGS
        confidence = CONFIDENCE_MEDIUM
        integrity_state = INTEGRITY_SPARSE_LOGS
    elif fallback and authoritative_status == column_status:
        authority_source = AUTHORITY_HYBRID
        confidence = CONFIDENCE_MEDIUM
        integrity_state = INTEGRITY_ALIGNED
    else:
        authority_source = AUTHORITY_ACTION_LOGS
        confidence = CONFIDENCE_HIGH
        integrity_state = INTEGRITY_ALIGNED

    return {
        'authority_source': authority_source,
        'reconciliation_confidence': confidence,
        'workflow_integrity_state': integrity_state,
        'missing_log_warning': missing,
        'fallback_to_columns': fallback or missing,
        'log_count': log_count,
    }


def _slice_reconciled_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Authoritative status + drift + workflow integrity (no ``raw``)."""
    if not raw:
        return {
            'authoritative_status': '',
            'column_status': '',
            'status_source': 'none',
            'drift_detected': False,
            'drift_reason': '',
            'workflow_integrity': build_workflow_integrity(
                log_count=0,
                authoritative_status='',
                column_status='',
                drift_detected=False,
                status_source='none',
            ),
        }

    drift = raw.get('drift') or {}
    auth = (raw.get('authoritative_status') or raw.get('derived_status') or '').strip()
    column = (
        (raw.get('column_status') or raw.get('shipment_status') or raw.get('movement_status') or '')
        .strip()
    )
    log_count = int((raw.get('timeline') or {}).get('log_count') or 0)
    drift_detected = bool(drift.get('has_drift'))
    reason = (drift.get('reason') or '') if drift_detected else ''

    if log_count > 0 and auth:
        source = AUTHORITY_ACTION_LOGS
    elif auth and not log_count:
        source = 'action_logs_inferred'
    else:
        source = AUTHORITY_COLUMNS_FALLBACK

    effective_auth = auth
    if not effective_auth and column:
        effective_auth = column

    integrity = build_workflow_integrity(
        log_count=log_count,
        authoritative_status=effective_auth,
        column_status=column,
        drift_detected=drift_detected,
        status_source=source,
    )

    return {
        'authoritative_status': effective_auth,
        'column_status': column,
        'status_source': source,
        'drift_detected': drift_detected,
        'drift_reason': reason,
        'workflow_integrity': integrity,
    }


def build_reconciliation_version(bundle: dict[str, Any]) -> str:
    """Stable token for cache invalidation when reconcile output changes."""
    ship = bundle.get('shipment') or {}
    mov = bundle.get('movement') or {}
    pod = bundle.get('pod_cod') or {}
    compliance = bundle.get('compliance_integrity') or {}
    return fingerprint_digest(
        {
            'shipment_auth': (ship.get('authoritative_status') or ''),
            'shipment_drift': ship.get('drift_detected'),
            'movement_auth': (mov.get('authoritative_status') or ''),
            'movement_drift': mov.get('drift_detected'),
            'compliance': compliance,
            'workflow_integrity': bundle.get('workflow_integrity'),
        }
    )


def build_workflow_projection_version_token(
    workflow_projection: dict[str, Any] | None,
) -> str:
    wf = workflow_projection or {}
    return fingerprint_digest(
        {
            'stage': (wf.get('current_stage') or '').strip(),
            'next': ((wf.get('next_action') or {}).get('action_code') or ''),
            'allowed': sorted(
                str(a.get('action_code') or '')
                for a in (wf.get('allowed_actions') or [])
                if isinstance(a, dict) and a.get('action_code')
            ),
        }
    )


def reconcile_dashboard_entities(
    context: DriverDashboardContext,
    *,
    request: Any | None = None,
    projection_cache: DashboardProjectionCache | None = None,
) -> dict[str, Any]:
    """
    Populate ``context.reconciliation`` using prefetched Action Logs when available.
    """
    from mobile_api.dashboard.services.dashboard_pod_cod_reconciler import (
        reconcile_pod_cod_compliance,
    )

    driver_id = booking_policy._driver_pk(context.driver)
    cache = projection_cache or get_projection_cache(context)

    bundle: dict[str, Any] = {
        'workflow_reconciled': True,
        'any_drift': False,
        'shipment': None,
        'movement': None,
        'pod_cod': {},
        'compliance_integrity': {},
        'reconciliation_version': '',
        'workflow_projection_version': (
            context.reconciliation.get('workflow_projection_version', '')
            if context.reconciliation
            else ''
        ),
        'compliance_projection_version': '',
    }

    ship_logs = cache.shipment_logs if cache else None
    mov_logs = cache.movement_logs if cache else None

    if context.active_shipment is not None:
        raw = reconcile_shipment_execution_state(
            context.active_shipment,
            movement=None,
            driver_id=driver_id,
            request=request,
            prefetched_logs=ship_logs,
        )
        state = _slice_reconciled_state(raw)
        state['raw'] = raw
        bundle['shipment'] = state
        if state.get('drift_detected'):
            bundle['any_drift'] = True
        wi = state.get('workflow_integrity') or {}
        if wi.get('missing_log_warning') or wi.get('fallback_to_columns'):
            bundle['any_drift'] = bundle['any_drift'] or wi.get(
                'missing_log_warning', False
            )

    if context.active_empty_movement is not None:
        raw_m = reconcile_movement_execution_state(
            context.active_empty_movement,
            driver_id=driver_id,
            request=request,
            prefetched_logs=mov_logs,
        )
        state_m = _slice_reconciled_state(raw_m)
        state_m['raw'] = raw_m
        bundle['movement'] = state_m
        if state_m.get('drift_detected'):
            bundle['any_drift'] = True

    pod_bundle = reconcile_pod_cod_compliance(context)
    bundle['compliance_integrity'] = pod_bundle.get('compliance_integrity') or {}
    bundle['compliance_projection_version'] = pod_bundle.get(
        'compliance_projection_version', ''
    )
    bundle['pod_cod_flags'] = pod_bundle.get('flags') or {}
    if bundle['compliance_integrity'].get('compliance_drift'):
        bundle['any_drift'] = True

    bundle['pod_cod'] = {
        'status_source': bundle['compliance_integrity'].get('authority_source', 'column'),
        'drift_detected': bundle['compliance_integrity'].get('compliance_drift', False),
        'drift_reason': ','.join(
            bundle['compliance_integrity'].get('drift_reasons') or []
        ),
    }

    bundle['workflow_integrity'] = _aggregate_workflow_integrity(bundle)
    bundle['reconciliation_version'] = build_reconciliation_version(bundle)

    context.reconciliation = bundle
    return bundle


def _aggregate_workflow_integrity(bundle: dict[str, Any]) -> dict[str, Any]:
    """Top-level integrity summary across shipment + movement + compliance."""
    ship_wi = (bundle.get('shipment') or {}).get('workflow_integrity') or {}
    mov_wi = (bundle.get('movement') or {}).get('workflow_integrity') or {}
    compliance = bundle.get('compliance_integrity') or {}

    missing = bool(
        ship_wi.get('missing_log_warning') or mov_wi.get('missing_log_warning')
    )
    fallback = bool(
        ship_wi.get('fallback_to_columns')
        or mov_wi.get('fallback_to_columns')
        or compliance.get('authority_source') == AUTHORITY_COLUMNS_FALLBACK
    )
    drift = bool(bundle.get('any_drift'))

    if missing:
        state = INTEGRITY_MISSING_LOGS
        confidence = CONFIDENCE_LOW
        source = AUTHORITY_COLUMNS_FALLBACK
    elif drift:
        state = INTEGRITY_DRIFT
        confidence = CONFIDENCE_MEDIUM
        source = AUTHORITY_ACTION_LOGS if not fallback else AUTHORITY_HYBRID
    else:
        state = INTEGRITY_ALIGNED
        confidence = CONFIDENCE_HIGH
        source = AUTHORITY_ACTION_LOGS

    return {
        'authority_source': source,
        'reconciliation_confidence': confidence,
        'workflow_integrity_state': state,
        'missing_log_warning': missing,
        'fallback_to_columns': fallback,
    }


def authoritative_shipment_status(context: DriverDashboardContext) -> str:
    block = (context.reconciliation or {}).get('shipment') or {}
    return (block.get('authoritative_status') or '').strip()


def authoritative_movement_status(context: DriverDashboardContext) -> str:
    block = (context.reconciliation or {}).get('movement') or {}
    return (block.get('authoritative_status') or '').strip()


def _overlay_status_from_block(block: dict[str, Any] | None) -> str | None:
    if not block:
        return None
    wi = block.get('workflow_integrity') or {}
    auth = (block.get('authoritative_status') or '').strip()
    if not auth:
        return None
    if wi.get('authority_source') == AUTHORITY_ACTION_LOGS and wi.get('log_count', 0) > 0:
        return auth
    if wi.get('fallback_to_columns') or wi.get('missing_log_warning'):
        return auth
    raw = block.get('raw') or {}
    if int((raw.get('timeline') or {}).get('log_count') or 0) > 0:
        return auth
    return auth if auth else None


@contextmanager
def apply_reconciled_status_overlays(
    context: DriverDashboardContext,
) -> Iterator[None]:
    """
    In-memory overlay of authoritative status for workflow/POD engines.

    Uses reconciled authoritative value (logs-first, explicit column fallback).
    """
    snapshots: list[tuple[Any, str, Any]] = []

    try:
        ship_block = (context.reconciliation or {}).get('shipment') or {}
        overlay_ship = _overlay_status_from_block(ship_block)
        if context.active_shipment is not None and overlay_ship is not None:
            s = context.active_shipment
            snapshots.append((s, 'shipment_status', getattr(s, 'shipment_status', None)))
            setattr(s, 'shipment_status', overlay_ship)

        mov_block = (context.reconciliation or {}).get('movement') or {}
        overlay_mov = _overlay_status_from_block(mov_block)
        if context.active_empty_movement is not None and overlay_mov is not None:
            m = context.active_empty_movement
            snapshots.append((m, 'status', getattr(m, 'status', None)))
            setattr(m, 'status', overlay_mov)

        yield
    finally:
        for obj, attr, old in reversed(snapshots):
            setattr(obj, attr, old)


def strip_raw_reconciliation_bundle(bundle: dict[str, Any] | None) -> dict[str, Any]:
    """API-safe reconciliation tree (no ``raw`` payloads)."""
    if not bundle:
        return {
            'workflow_reconciled': True,
            'drift_detected': False,
            'shipment': None,
            'movement': None,
            'pod_cod': {},
            'workflow_integrity': {},
            'compliance_integrity': {},
        }
    out: dict[str, Any] = {
        'workflow_reconciled': bool(bundle.get('workflow_reconciled', True)),
        'drift_detected': bool(bundle.get('any_drift')),
        'pod_cod': dict(bundle.get('pod_cod') or {}),
        'workflow_integrity': dict(bundle.get('workflow_integrity') or {}),
        'compliance_integrity': dict(bundle.get('compliance_integrity') or {}),
        'reconciliation_version': bundle.get('reconciliation_version', ''),
        'workflow_projection_version': bundle.get('workflow_projection_version', ''),
        'compliance_projection_version': bundle.get(
            'compliance_projection_version', ''
        ),
    }
    for key in ('shipment', 'movement'):
        block = bundle.get(key)
        if not isinstance(block, dict):
            out[key] = None
            continue
        out[key] = {
            k: block[k]
            for k in (
                'authoritative_status',
                'column_status',
                'status_source',
                'drift_detected',
                'drift_reason',
                'workflow_integrity',
            )
            if k in block
        }
    return out


def workflow_reconciliation_extras(context: DriverDashboardContext) -> dict[str, Any]:
    """Drift summary nested under ``workflow.workflow_metadata``."""
    b = context.reconciliation or {}
    ship = b.get('shipment') if isinstance(b.get('shipment'), dict) else {}
    mov = b.get('movement') if isinstance(b.get('movement'), dict) else {}
    return {
        'drift_detected': bool(b.get('any_drift')),
        'shipment_authoritative_status': (ship.get('authoritative_status') or ''),
        'movement_authoritative_status': (mov.get('authoritative_status') or ''),
        'workflow_integrity': dict(b.get('workflow_integrity') or {}),
    }
