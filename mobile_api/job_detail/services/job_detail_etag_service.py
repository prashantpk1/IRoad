"""
mobile_api/job_detail/services/job_detail_etag_service.py

Content hash and ETag helpers for Job Detail polling.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.services.dashboard_etag_service import (
    _entity_id,
    _stable_json,
    build_etag_from_fingerprint,
    etag_matches_request,
    fingerprint_digest,
    pod_cod_fingerprint_tuple,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    authoritative_entity_status,
)

__all__ = [
    'build_etag_from_fingerprint',
    'build_content_fingerprint',
    'build_invalidation_fingerprint',
    'etag_matches_request',
    'fingerprint_digest',
    'JOB_DETAIL_NAVIGATION_CONTRACT_VERSION',
]

JOB_DETAIL_NAVIGATION_CONTRACT_VERSION = '6'


def _reconciliation_versions(context: JobDetailContext) -> dict[str, str]:
    recon = context.reconciliation or {}
    pod_bundle = recon.get('pod_cod') or {}
    return {
        'reconciliation_version': (recon.get('reconciliation_version') or '').strip(),
        'compliance_projection_version': (
            pod_bundle.get('compliance_projection_version') or ''
        ).strip(),
    }


def _pod_flags_for_fingerprint(context: JobDetailContext) -> dict[str, bool]:
    pod = context.pod_cod or {}
    return {k: v for k, v in pod.items() if isinstance(v, bool)}


def build_invalidation_fingerprint(
    context: JobDetailContext,
    *,
    latest_action_log_id: str = '',
) -> dict[str, Any]:
    """Pre-projection invalidation inputs (entity + logs + compliance)."""
    auth_status = authoritative_entity_status(context)
    pod_flags = _pod_flags_for_fingerprint(context)
    recon = context.reconciliation or {}

    entity_id = ''
    column_status = ''
    if context.job_type == 'shipment' and context.shipment is not None:
        entity_id = _entity_id(context.shipment)
        column_status = str(
            getattr(context.shipment, 'shipment_status', '') or ''
        ).strip()
    elif context.job_type == 'movement' and context.movement is not None:
        entity_id = _entity_id(context.movement)
        column_status = str(getattr(context.movement, 'status', '') or '').strip()

    booking_id = _entity_id(context.booking) if context.booking is not None else ''

    return {
        'tenant_schema': (context.tenant_schema or '').strip(),
        'user_id': (context.user_id or '').strip(),
        'job_type': context.job_type,
        'job_id': (context.job_id or '').strip(),
        'entity_id': entity_id,
        'booking_id': booking_id,
        'authoritative_status': auth_status or column_status,
        'column_status': column_status,
        'latest_action_log_id': (
            latest_action_log_id or context.latest_action_log_id or ''
        ).strip(),
        'pod_cod': pod_cod_fingerprint_tuple(pod_flags or None),
        'round_trip_stage': (
            (context.round_trip or {}).get('booking_execution_stage') or ''
        ).strip(),
        'any_drift': bool(recon.get('any_drift')),
        **_reconciliation_versions(context),
    }


def build_content_fingerprint(
    context: JobDetailContext,
    *,
    latest_action_log_id: str = '',
) -> dict[str, Any]:
    """Full response fingerprint including workflow and timeline head."""
    fp = build_invalidation_fingerprint(
        context,
        latest_action_log_id=latest_action_log_id,
    )
    workflow = context.workflow or {}
    next_action = workflow.get('next_action') or {}
    primary = workflow.get('primary_action') or {}
    fp['allowed_action_count'] = len(workflow.get('allowed_actions') or [])
    fp['workflow_stage'] = (workflow.get('current_stage') or '').strip()
    fp['next_action_code'] = str(
        next_action.get('action_code') or primary.get('action_code') or ''
    ).strip()
    fp['allowed_action_codes'] = sorted(
        str(item.get('action_code') or '').strip()
        for item in (workflow.get('allowed_actions') or [])
        if isinstance(item, dict) and (item.get('action_code') or '').strip()
    )
    fp['booking_item_type'] = str(workflow.get('booking_item_type') or '').strip()
    timeline = context.timeline or {}
    fp['timeline_preview_count'] = len(timeline.get('timeline_preview') or [])
    fp['timeline_cursor'] = (timeline.get('timeline_cursor') or '').strip()
    fp['navigation_contract_version'] = JOB_DETAIL_NAVIGATION_CONTRACT_VERSION
    wi = (context.reconciliation or {}).get('workflow_integrity') or {}
    fp['workflow_integrity_state'] = (wi.get('workflow_integrity_state') or '').strip()
    fp.update(_reconciliation_versions(context))
    return fp
