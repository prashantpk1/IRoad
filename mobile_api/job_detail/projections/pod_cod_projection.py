"""
mobile_api/job_detail/projections/pod_cod_projection.py

``pod_cod`` section — shipment jobs only (empty moves omit).

Column flags from ``pod_cod_policy``; cross-checked with Action Logs via
``reconcile_job_detail_pod_cod``. Display may prefer log evidence when authoritative.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import pod_cod_policy as policy
from mobile_api.helpers.cod_amount import build_cod_payment_display
from mobile_api.pod_capture.services.pod_section_metadata import (
    build_hard_copy_confirmation_block,
)
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
        tenant_schema=(context.tenant_schema or '').strip(),
    )
    display_flags['compliance_integrity'] = integrity
    display_flags.update(
        build_cod_payment_display(
            shipment=context.shipment,
            booking=context.booking,
        ),
    )
    display_flags['hard_copy_confirmation'] = build_hard_copy_confirmation_block(
        context.shipment,
        driver=context.driver,
        tenant_schema=(context.tenant_schema or '').strip(),
        log_evidence=evidence,
    )
    display_flags['pod_type'] = (getattr(context.shipment, 'pod_type', None) or '').strip()
    return display_flags


def _resolve_display_flags(
    shipment: Any,
    column_flags: dict[str, bool],
    evidence: dict[str, bool],
    integrity: dict[str, Any],
    *,
    driver: Any | None,
    tenant_schema: str = '',
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

    hard_pod_shipment = policy.shipment_requires_hard_copy(shipment)
    hard_pod_log = bool(evidence.get('hard_pod_log', False))
    custody_complete = policy.is_hard_pod_custody_complete(
        shipment,
        log_evidence=evidence,
        tenant_schema=tenant_schema,
        driver=driver,
    )

    if log_primary or evidence.get('pod_uploaded'):
        if evidence.get('pod_uploaded'):
            flags['pod_pending'] = False
            if hard_pod_shipment:
                flags['hard_pod_pending'] = not custody_complete
                flags['pod_compliant'] = custody_complete and (
                    hard_pod_log or evidence.get('pod_uploaded')
                )
            else:
                flags['pod_compliant'] = True
                flags['hard_pod_pending'] = False
    elif hard_pod_shipment and not custody_complete:
        flags['hard_pod_pending'] = policy.derive_hard_pod_pending(
            shipment,
            log_evidence=evidence,
            tenant_schema=tenant_schema,
        )

    if log_primary or evidence.get('cod_collected_log'):
        if evidence.get('cod_collected_log') and policy.is_cod_shipment(shipment):
            flags['cod_pending'] = False
            flags['cod_collected'] = True

    flags['treasury_pending'] = policy.derive_treasury_pending(
        shipment,
        driver=driver,
    )
    flags['delivery_blocked'] = policy.derive_delivery_blocked(shipment)
    if flags.get('pod_compliant') and (
        not policy.is_cod_shipment(shipment) or flags.get('cod_collected')
    ):
        flags['delivery_blocked'] = False
    return flags
