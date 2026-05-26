"""
mobile_api/dashboard/services/dashboard_pod_cod_reconciler.py

Read-only POD/COD/treasury compliance reconciliation for the driver dashboard.

Cross-checks column-backed flags with Action Log evidence (POD upload, COD
collection) and treasury helpers — no DB writes.
"""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantShipment

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.dashboard.services.dashboard_etag_service import (
    fingerprint_digest,
    pod_cod_fingerprint_tuple,
)
from mobile_api.dashboard.services.dashboard_projection_cache import (
    get_projection_cache,
)

from iroad_tenants.operation_runtime.impacts import operation_action_matches


def _logs_for_shipment(context: DriverDashboardContext) -> list[Any]:
    cache = get_projection_cache(context)
    if cache is not None and cache.shipment_logs:
        return cache.shipment_logs
    return []


def _log_evidence_flags(logs: list[Any]) -> dict[str, bool]:
    """Derive compliance signals from append-only Action Log rows."""
    pod_uploaded = False
    cod_collected_log = False
    delivered_log = False
    hard_pod_log = False

    for log in logs:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        if operation_action_matches(
            action,
            'pod',
            'upload pod',
            'a8',
            'action 8',
            'submit pod',
        ):
            pod_uploaded = True
        if operation_action_matches(
            action,
            'collect payment',
            'a9',
            'action 9',
            'cod',
        ):
            cod_collected_log = True
        if operation_action_matches(
            action,
            'deliver',
            'a7',
            'action 7',
            'delivered',
        ):
            delivered_log = True
        if operation_action_matches(
            action,
            'hard pod',
            'hard copy',
            'hardcopy',
        ):
            hard_pod_log = True

    return {
        'pod_uploaded': pod_uploaded,
        'cod_collected_log': cod_collected_log,
        'delivered_log': delivered_log,
        'hard_pod_log': hard_pod_log,
    }


def _detect_compliance_drift(
    shipment: Any,
    column_flags: dict[str, bool],
    evidence: dict[str, bool],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    pod_status = (getattr(shipment, 'pod_status', None) or '').strip()
    is_cod = pod_cod_policy.is_cod_shipment(shipment)

    if evidence['cod_collected_log'] and column_flags.get('cod_pending'):
        reasons.append('cod_collected_log_but_column_pending')
    if column_flags.get('cod_collected') and not evidence['cod_collected_log']:
        reasons.append('cod_collected_column_without_collection_log')
    if column_flags.get('treasury_pending') and evidence['cod_collected_log']:
        reasons.append('cod_collected_log_but_treasury_pending')

    if evidence['pod_uploaded'] and column_flags.get('pod_pending'):
        reasons.append('pod_uploaded_log_but_column_pending')
    if pod_status in {
        TenantShipment.PodStatus.COMPLIANT,
        TenantShipment.PodStatus.HARD_COPY_RECEIVED,
    } and not evidence['pod_uploaded']:
        reasons.append('pod_compliant_column_without_upload_log')

    if status in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    } and column_flags.get('pod_pending'):
        reasons.append('delivered_but_pod_pending')

    if evidence['delivered_log'] and status not in {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
    }:
        reasons.append('delivered_log_but_shipment_not_delivered')

    if column_flags.get('hard_pod_pending') and evidence['hard_pod_log']:
        reasons.append('hard_pod_log_mismatch')

    if is_cod and evidence['delivered_log'] and column_flags.get('cod_pending'):
        reasons.append('delivered_log_but_cod_still_pending')

    return bool(reasons), reasons


def build_compliance_projection_version(
    integrity: dict[str, Any],
    flags: dict[str, bool],
) -> str:
    return fingerprint_digest(
        {
            'integrity': integrity,
            'flags': pod_cod_fingerprint_tuple(flags),
        }
    )


def reconcile_pod_cod_compliance(
    context: DriverDashboardContext,
) -> dict[str, Any]:
    """
    Reconcile POD/COD/treasury for the active shipment.

    Returns ``compliance_integrity`` plus merged ``flags`` for projection.
    """
    shipment = context.active_shipment
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
            'compliance_projection_version': fingerprint_digest(empty_integrity),
        }

    logs = _logs_for_shipment(context)
    evidence = _log_evidence_flags(logs)
    column_flags = dict(
        pod_cod_policy.derive_pod_cod_flags(shipment, driver=context.driver)
    )
    log_count = len(logs)

    has_log_authority = log_count > 0
    drift, drift_reasons = _detect_compliance_drift(
        shipment,
        column_flags,
        evidence,
    )

    pod_reconciled = not drift or not any(
        r.startswith('pod_') for r in drift_reasons
    )
    cod_reconciled = not drift or not any(
        r.startswith('cod_') for r in drift_reasons
    )
    treasury_reconciled = 'treasury' not in ' '.join(drift_reasons)

    integrity = {
        'pod_reconciled': pod_reconciled,
        'cod_reconciled': cod_reconciled,
        'treasury_reconciled': treasury_reconciled,
        'compliance_drift': drift,
        'drift_reasons': drift_reasons,
        'authority_source': 'action_logs' if has_log_authority else 'columns_fallback',
        'log_evidence': evidence,
    }

    version = build_compliance_projection_version(integrity, column_flags)

    return {
        'compliance_integrity': integrity,
        'flags': column_flags,
        'compliance_projection_version': version,
    }
