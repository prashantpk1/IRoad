"""
mobile_api/dashboard/services/dashboard_sync_metadata.py

Offline sync metadata for the driver dashboard (read-only, server-side).
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.services.dashboard_etag_service import (
    _entity_id,
    build_content_fingerprint,
    fingerprint_digest,
    pod_cod_fingerprint_tuple,
)
from mobile_api.dashboard.services.dashboard_status_reconciler import (
    authoritative_movement_status,
    authoritative_shipment_status,
    strip_raw_reconciliation_bundle,
)

DASHBOARD_PROJECTION_VERSION = '2'

WORKFLOW_VERSION_SCHEME = '2'


def _workflow_action_code(workflow: dict[str, Any]) -> str:
    next_action = workflow.get('next_action') or {}
    primary = workflow.get('primary_action') or {}
    return str(
        next_action.get('action_code')
        or primary.get('action_code')
        or ''
    ).strip()


def _sorted_allowed_action_codes(workflow: dict[str, Any]) -> list[str]:
    codes = [
        str(item.get('action_code') or '').strip()
        for item in (workflow.get('allowed_actions') or [])
        if isinstance(item, dict)
    ]
    return sorted(c for c in codes if c)


def build_workflow_version(context: DriverDashboardContext) -> str:
    workflow = context.workflow_projection or {}
    recon = context.reconciliation or {}
    wi = recon.get('workflow_integrity') or {}
    payload = {
        'scheme': WORKFLOW_VERSION_SCHEME,
        'stage': (workflow.get('current_stage') or '').strip(),
        'next_action_code': _workflow_action_code(workflow),
        'allowed_action_codes': _sorted_allowed_action_codes(workflow),
        'workflow_source': (workflow.get('workflow_source') or '').strip(),
        'authority_source': wi.get('authority_source', ''),
        'integrity_state': wi.get('workflow_integrity_state', ''),
        'reconciliation_version': recon.get('reconciliation_version', ''),
    }
    return fingerprint_digest(payload)


def build_entity_versions(
    context: DriverDashboardContext,
    *,
    latest_action_log_id: str = '',
) -> dict[str, str]:
    """
    Per-entity version tokens from **reconciled** authoritative state.
    """
    booking = context.active_booking
    shipment = context.active_shipment
    movement = context.active_empty_movement
    selection = context.booking_selection
    recon = context.reconciliation or {}
    pod = context.pod_cod_projection or {}
    pod_flags = {k: v for k, v in pod.items() if isinstance(v, bool)}
    ship_auth = authoritative_shipment_status(context)
    mov_auth = authoritative_movement_status(context)
    wi = recon.get('workflow_integrity') or {}

    versions: dict[str, str] = {
        'booking': '',
        'shipment': '',
        'movement': '',
        'action_log': (latest_action_log_id or context.latest_action_log_id or '').strip(),
        'pod_cod': '',
    }

    if booking is not None:
        versions['booking'] = fingerprint_digest(
            {
                'id': _entity_id(booking),
                'status': str(getattr(booking, 'booking_status', '') or '').strip(),
                'stage': (
                    (selection.booking_execution_stage or '').strip()
                    if selection
                    else ''
                ),
                'exec_progress': (
                    selection.execution_progress_percentage if selection else 0
                ),
            }
        )

    if shipment is not None:
        versions['shipment'] = fingerprint_digest(
            {
                'id': _entity_id(shipment),
                'authoritative_status': ship_auth,
                'column_status': str(
                    getattr(shipment, 'shipment_status', '') or ''
                ).strip(),
                'line': str(getattr(shipment, 'booking_item_type', '') or '').strip(),
                'integrity': wi.get('workflow_integrity_state', ''),
            }
        )

    if movement is not None:
        versions['movement'] = fingerprint_digest(
            {
                'id': _entity_id(movement),
                'authoritative_status': mov_auth,
                'column_status': str(getattr(movement, 'status', '') or '').strip(),
                'stage': (
                    (context.empty_move_selection.movement_stage or '').strip()
                    if context.empty_move_selection
                    else ''
                ),
            }
        )

    if pod_flags or recon.get('compliance_integrity'):
        versions['pod_cod'] = fingerprint_digest(
            {
                'flags': pod_cod_fingerprint_tuple(pod_flags),
                'compliance': recon.get('compliance_integrity') or {},
                'compliance_version': recon.get('compliance_projection_version', ''),
            }
        )

    return versions


def resolve_content_hash(context: DriverDashboardContext) -> str:
    existing = (context.content_hash or '').strip()
    if existing:
        return existing

    pod = {
        k: v
        for k, v in (context.pod_cod_projection or {}).items()
        if isinstance(v, bool)
    }
    fp = build_content_fingerprint(
        context,
        latest_action_log_id=context.latest_action_log_id,
        pod_cod=pod or None,
    )
    return fingerprint_digest(fp)


def build_driver_dashboard_sync_metadata(
    context: DriverDashboardContext,
) -> dict[str, Any]:
    now = timezone.now()
    log_id = (context.latest_action_log_id or '').strip()
    content_hash = resolve_content_hash(context)
    recon = context.reconciliation or {}
    wi = recon.get('workflow_integrity') or {}

    meta: dict[str, Any] = {
        'dashboard_projection_version': DASHBOARD_PROJECTION_VERSION,
        'generated_at': now.isoformat(),
        'last_action_log_id': log_id,
        'content_hash': content_hash,
        'workflow_version': build_workflow_version(context),
        'server_time': now.isoformat(),
        'entity_versions': build_entity_versions(
            context,
            latest_action_log_id=log_id,
        ),
        'workflow_integrity': dict(wi),
        'compliance_integrity': dict(recon.get('compliance_integrity') or {}),
        'reconciliation_version': recon.get('reconciliation_version', ''),
        'workflow_projection_version': recon.get('workflow_projection_version', ''),
        'compliance_projection_version': recon.get(
            'compliance_projection_version', ''
        ),
    }

    workflow = context.workflow_projection or {}
    meta['workflow_source'] = (workflow.get('workflow_source') or '').strip()
    meta['allowed_action_count'] = len(workflow.get('allowed_actions') or [])
    meta['workflow_reconciled'] = True
    meta['drift_detected'] = bool(recon.get('any_drift'))
    meta['dashboard_etag'] = (context.dashboard_etag or '').strip()
    meta['tenant_schema'] = (context.tenant_schema or '').strip()
    meta['user_id'] = (context.user_id or '').strip()
    meta['reconciliation'] = strip_raw_reconciliation_bundle(recon)
    if context.active_booking is not None:
        meta['booking_id'] = _entity_id(context.active_booking)
    if context.active_shipment is not None:
        meta['shipment_id'] = _entity_id(context.active_shipment)
    if context.active_empty_movement is not None:
        meta['movement_id'] = _entity_id(context.active_empty_movement)

    return meta
