"""
mobile_api/job_detail/projections/pod_cod_projection.py

``pod_cod`` section — shipment jobs only (empty moves omit).

Column flags from ``pod_cod_policy``; cross-checked with Action Logs via
``reconcile_job_detail_pod_cod``. Display may prefer log evidence when authoritative.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import pod_cod_policy as policy
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_pod_cod_reconciler import (
    reconcile_job_detail_pod_cod,
)
from tenant_workspace.models import TenantShipment

_EMPTY_POD_COD: dict[str, Any] = {
    'pod_pending': False,
    'pod_compliant': False,
    'hard_pod_pending': False,
    'cod_pending': False,
    'cod_collected': False,
    'treasury_pending': False,
    'delivery_blocked': False,
    'compliance_integrity': {},
}


def build_pod_cod_section(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Build POD/COD/treasury summary for shipment Job Detail.

    Uses reconciliation bundle when present; otherwise runs reconcile (requires cache).
    """
    _ = request
    if context.job_type != 'shipment':
        return {}
    if context.shipment is None:
        return dict(_EMPTY_POD_COD)

    pod_bundle = (context.reconciliation or {}).get('pod_cod')
    if not pod_bundle:
        pod_bundle = reconcile_job_detail_pod_cod(context)

    column_flags = dict(pod_bundle.get('flags') or {})
    evidence = dict(pod_bundle.get('log_evidence') or {})
    integrity = dict(pod_bundle.get('compliance_integrity') or {})

    display_flags = _resolve_display_flags(
        context.shipment,
        column_flags,
        evidence,
        integrity,
        driver=context.driver,
    )
    display_flags['compliance_integrity'] = integrity
    return display_flags


def _resolve_display_flags(
    shipment: Any,
    column_flags: dict[str, bool],
    evidence: dict[str, bool],
    integrity: dict[str, Any],
    *,
    driver: Any | None,
) -> dict[str, bool]:
    """
    Merge column flags with Action Log evidence when logs are authoritative.

    Does not mutate ORM columns — adjusts outward booleans only.
    """
    flags = dict(column_flags)
    has_logs = int(integrity.get('log_count') or 0) > 0
    log_primary = integrity.get('authority_source') == 'action_logs' or (
        has_logs and not integrity.get('compliance_drift')
    )

    pod_complete = policy.pod_status_is_complete(
        getattr(shipment, 'pod_status', None),
    )
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    hard_pod_type = pod_type == TenantShipment.PodType.HARD.casefold()
    hard_pod_log = bool(evidence.get('hard_pod_log', False))

    if log_primary or evidence.get('pod_uploaded'):
        if evidence.get('pod_uploaded'):
            flags['pod_pending'] = False
            if hard_pod_type:
                flags['hard_pod_pending'] = (
                    not pod_complete and hard_pod_type and not hard_pod_log
                )
                flags['pod_compliant'] = pod_complete or hard_pod_log
            else:
                flags['pod_compliant'] = True
                flags['hard_pod_pending'] = False

    if pod_complete and hard_pod_type:
        flags['hard_pod_pending'] = False
        flags['pod_compliant'] = True

    if log_primary or evidence.get('cod_collected_log'):
        if evidence.get('cod_collected_log') and policy.is_cod_shipment(shipment):
            flags['cod_pending'] = False
            flags['cod_collected'] = True

    flags['treasury_pending'] = policy.derive_treasury_pending(
        shipment,
        driver=driver,
    )
    flags['delivery_blocked'] = policy.derive_delivery_blocked(shipment)
    return flags
