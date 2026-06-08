"""
mobile_api/job_detail/services/job_detail_pod_cod_reconciler.py

Read-only POD/COD/treasury reconciliation for explicit shipment Job Detail.

Reuses dashboard compliance helpers (Action Log evidence + column cross-check).
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.dashboard.services.dashboard_pod_cod_reconciler import (
    _detect_compliance_drift,
    _log_evidence_flags,
    build_compliance_projection_version,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_projection_cache import (
    get_projection_cache,
)


def _logs_for_shipment(context: JobDetailContext) -> list[Any]:
    cache = get_projection_cache(context)
    if cache is not None and cache.shipment_logs:
        return cache.shipment_logs
    return []


def reconcile_job_detail_pod_cod(context: JobDetailContext) -> dict[str, Any]:
    """
    Reconcile POD/COD/treasury for ``context.shipment``.

    Returns column-derived flags, log evidence, and ``compliance_integrity``.
    """
    shipment = context.shipment
    if shipment is None:
        empty_integrity = {
            'pod_reconciled': True,
            'cod_reconciled': True,
            'treasury_reconciled': True,
            'compliance_drift': False,
            'drift_reasons': [],
            'authority_source': 'none',
        }
        return {
            'compliance_integrity': empty_integrity,
            'flags': dict(pod_cod_policy.derive_pod_cod_flags(None)),
            'log_evidence': {},
            'compliance_projection_version': build_compliance_projection_version(
                empty_integrity,
                {},
            ),
        }

    logs = _logs_for_shipment(context)
    evidence = _log_evidence_flags(logs)
    column_flags = dict(
        pod_cod_policy.derive_pod_cod_flags(
            shipment,
            driver=context.driver,
            log_evidence=evidence,
        )
    )
    log_count = len(logs)

    drift, drift_reasons = _detect_compliance_drift(
        shipment,
        column_flags,
        evidence,
    )

    integrity = {
        'pod_reconciled': not drift
        or not any(r.startswith('pod_') for r in drift_reasons),
        'cod_reconciled': not drift
        or not any(r.startswith('cod_') for r in drift_reasons),
        'treasury_reconciled': 'treasury' not in ' '.join(drift_reasons),
        'compliance_drift': drift,
        'drift_reasons': drift_reasons,
        'authority_source': 'action_logs' if log_count > 0 else 'columns_fallback',
        'log_evidence': evidence,
        'log_count': log_count,
    }

    version = build_compliance_projection_version(integrity, column_flags)

    return {
        'compliance_integrity': integrity,
        'flags': column_flags,
        'log_evidence': evidence,
        'compliance_projection_version': version,
    }
