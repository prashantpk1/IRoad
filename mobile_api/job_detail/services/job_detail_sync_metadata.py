"""
mobile_api/job_detail/services/job_detail_sync_metadata.py

Offline sync metadata for explicit Job Detail (read-only).
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from mobile_api.dashboard.services.dashboard_etag_service import _entity_id
from mobile_api.job_detail.constants import JOB_DETAIL_ETAG_ENABLED
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_etag_service import (
    build_content_fingerprint,
    build_etag_from_fingerprint,
    build_invalidation_fingerprint,
    etag_matches_request,
    fingerprint_digest,
    pod_cod_fingerprint_tuple,
)
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    authoritative_entity_status,
)

JOB_DETAIL_PROJECTION_VERSION = '2'
WORKFLOW_VERSION_SCHEME = '1'


def _workflow_action_code(workflow: dict[str, Any]) -> str:
    next_action = workflow.get('next_action') or {}
    primary = workflow.get('primary_action') or {}
    return str(
        next_action.get('action_code') or primary.get('action_code') or ''
    ).strip()


def _sorted_allowed_action_codes(workflow: dict[str, Any]) -> list[str]:
    codes = [
        str(item.get('action_code') or '').strip()
        for item in (workflow.get('allowed_actions') or [])
        if isinstance(item, dict)
    ]
    return sorted(c for c in codes if c)


def build_workflow_version(context: JobDetailContext) -> str:
    workflow = context.workflow or {}
    recon = context.reconciliation or {}
    wi = recon.get('workflow_integrity') or {}
    payload = {
        'scheme': WORKFLOW_VERSION_SCHEME,
        'job_type': context.job_type,
        'stage': (workflow.get('current_stage') or '').strip(),
        'next_action_code': _workflow_action_code(workflow),
        'allowed_action_codes': _sorted_allowed_action_codes(workflow),
        'workflow_source': (workflow.get('workflow_source') or '').strip(),
        'authority_source': wi.get('authority_source', ''),
        'integrity_state': wi.get('workflow_integrity_state', ''),
        'reconciliation_version': recon.get('reconciliation_version', ''),
    }
    return fingerprint_digest(payload)


def build_entity_versions(context: JobDetailContext) -> dict[str, str]:
    """Per-entity version tokens from reconciled authoritative state."""
    recon = context.reconciliation or {}
    pod_bundle = recon.get('pod_cod') or {}
    pod_flags = dict(pod_bundle.get('flags') or {})
    pod_display = {
        k: v for k, v in (context.pod_cod or {}).items() if isinstance(v, bool)
    }
    if not pod_display:
        pod_display = pod_flags
    wi = recon.get('workflow_integrity') or {}
    auth_status = authoritative_entity_status(context)

    versions: dict[str, str] = {
        'booking': '',
        'shipment': '',
        'movement': '',
        'action_log': (context.latest_action_log_id or '').strip(),
        'pod_cod': '',
    }

    if context.booking is not None:
        versions['booking'] = fingerprint_digest(
            {
                'id': _entity_id(context.booking),
                'status': str(
                    getattr(context.booking, 'booking_status', '') or ''
                ).strip(),
                'stage': (
                    (context.round_trip or {}).get('booking_execution_stage') or ''
                ).strip(),
            }
        )

    if context.shipment is not None:
        versions['shipment'] = fingerprint_digest(
            {
                'id': _entity_id(context.shipment),
                'authoritative_status': auth_status,
                'column_status': str(
                    getattr(context.shipment, 'shipment_status', '') or ''
                ).strip(),
                'line': str(
                    getattr(context.shipment, 'booking_item_type', '') or ''
                ).strip(),
                'integrity': wi.get('workflow_integrity_state', ''),
            }
        )

    if context.movement is not None:
        versions['movement'] = fingerprint_digest(
            {
                'id': _entity_id(context.movement),
                'authoritative_status': auth_status,
                'column_status': str(
                    getattr(context.movement, 'status', '') or ''
                ).strip(),
            }
        )

    if pod_display or recon.get('compliance_integrity'):
        versions['pod_cod'] = fingerprint_digest(
            {
                'flags': pod_cod_fingerprint_tuple(pod_display),
                'compliance': recon.get('compliance_integrity') or {},
                'compliance_version': pod_bundle.get(
                    'compliance_projection_version', ''
                ),
            }
        )

    return versions


def resolve_content_hash(context: JobDetailContext) -> str:
    existing = (context.content_hash or '').strip()
    if existing:
        return existing
    pod_flags = {k: v for k, v in (context.pod_cod or {}).items() if isinstance(v, bool)}
    fp = build_content_fingerprint(
        context,
        latest_action_log_id=context.latest_action_log_id,
    )
    if pod_flags:
        fp['pod_cod'] = pod_cod_fingerprint_tuple(pod_flags)
    return fingerprint_digest(fp)


def build_job_detail_sync_metadata(context: JobDetailContext) -> dict[str, Any]:
    """
    Canonical ``sync_metadata`` contract for Job Detail responses.

    Required keys: ``content_hash``, ``entity_versions``, ``workflow_version``,
    ``generated_at``.
    """
    now = timezone.now()
    recon = context.reconciliation or {}
    wi = recon.get('workflow_integrity') or {}

    return {
        'job_detail_projection_version': JOB_DETAIL_PROJECTION_VERSION,
        'content_hash': resolve_content_hash(context),
        'entity_versions': build_entity_versions(context),
        'workflow_version': build_workflow_version(context),
        'generated_at': now.isoformat(),
        'last_action_log_id': (context.latest_action_log_id or '').strip(),
        'workflow_integrity': dict(wi),
        'compliance_integrity': dict(recon.get('compliance_integrity') or {}),
        'reconciliation_version': recon.get('reconciliation_version', ''),
        'workflow_reconciled': bool(recon.get('workflow_reconciled')),
        'drift_detected': bool(recon.get('any_drift')),
        'job_etag': (context.job_etag or '').strip(),
        'tenant_schema': (context.tenant_schema or '').strip(),
        'job_type': context.job_type,
        'job_id': context.job_id,
    }


def finalize_job_detail_sync(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> None:
    """
    Attach ``content_hash``, ``job_etag``, and ``sync_metadata`` on context.

    Call once after all projections are built (single pass).
    """
    content_fp = build_content_fingerprint(
        context,
        latest_action_log_id=context.latest_action_log_id,
    )
    context.content_hash = fingerprint_digest(content_fp)
    context.job_etag = build_etag_from_fingerprint(content_fp)
    context.sync_metadata = build_job_detail_sync_metadata(context)

    if (
        JOB_DETAIL_ETAG_ENABLED
        and request is not None
        and etag_matches_request(request, context.job_etag)
    ):
        context.poll_not_modified = True


def should_short_circuit_polling(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> bool:
    """
    Skip heavy projections when ``If-None-Match`` matches invalidation ETag.

    Sets ``poll_not_modified`` and ``job_etag`` on the context when true.
    """
    if not JOB_DETAIL_ETAG_ENABLED or request is None:
        return False
    inv = build_invalidation_fingerprint(context)
    etag = build_etag_from_fingerprint(inv)
    if not etag_matches_request(request, etag):
        return False
    context.job_etag = etag
    context.content_hash = fingerprint_digest(inv)
    context.poll_not_modified = True
    return True
