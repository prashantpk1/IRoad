"""
mobile_api/hard_pod/services/hard_pod_reconciliation_service.py

Read-only reconciliation between mobile custody, Action Log evidence, and portal POD columns.
"""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantShipment

from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.hard_pod.services.custody_authority_service import (
    HardPodCustodyAuthorityService,
)
from mobile_api.hard_pod.projections.hard_pod_projection_builder import (
    CUSTODY_COLLECTED,
    CUSTODY_NOT_STARTED,
    CUSTODY_VERIFIED,
)


def reconcile_hard_pod_row(
    *,
    shipment: Any,
    column_flags: dict[str, bool],
    log_evidence: dict[str, bool],
    custody_state: str,
    verification_state: str,
    portal_pod: dict[str, Any],
) -> dict[str, bool]:
    """
    Per-shipment reconciliation flags for the Hard POD list.

    Does not mutate shipment or workflow state.
    """
    hard_pod_pending = bool(column_flags.get('hard_pod_pending'))
    hard_pod_log = bool(log_evidence.get('hard_pod_log'))
    pod_status = (getattr(shipment, 'pod_status', None) or '').strip()
    portal_complete = pod_status in {
        TenantShipment.PodStatus.COMPLETED,
    }
    portal_location = (portal_pod.get('physical_location') or '').strip()

    custody_advanced = custody_state not in {
        CUSTODY_NOT_STARTED,
        '',
    }
    custody_complete = (
        custody_state == CUSTODY_VERIFIED or verification_state == 'verified'
    )

    missing_hard_pod_log = (
        custody_advanced
        and not hard_pod_log
        and hard_pod_pending
    )

    custody_vs_workflow_mismatch = False
    if hard_pod_log and hard_pod_pending:
        custody_vs_workflow_mismatch = True
    if custody_complete and hard_pod_pending and not hard_pod_log:
        custody_vs_workflow_mismatch = True
    if custody_advanced and portal_complete and not hard_pod_log:
        custody_vs_workflow_mismatch = True
    if (
        custody_state == CUSTODY_COLLECTED
        and portal_location
        and portal_location.casefold() not in {'with driver', 'not collected', ''}
        and not hard_pod_log
    ):
        custody_vs_workflow_mismatch = True

    portal_vs_custody_mismatch = (
        portal_complete
        and custody_state == CUSTODY_NOT_STARTED
        and not custody_advanced
    )

    if portal_vs_custody_mismatch and not custody_vs_workflow_mismatch:
        custody_vs_workflow_mismatch = True

    authority = HardPodCustodyAuthorityService().resolve_authority(
        tenant_schema=str(getattr(shipment, 'tenant_schema', '') or '').strip(),
        shipment_id=str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', '') or '').strip(),
        driver_id=str(getattr(getattr(shipment, 'driver', None), 'pk', '') or getattr(shipment, 'driver_id', '') or '').strip(),
    )

    return {
        'custody_vs_workflow_mismatch': custody_vs_workflow_mismatch,
        'missing_hard_pod_log': missing_hard_pod_log,
        'portal_vs_custody_mismatch': portal_vs_custody_mismatch,
        'custody_authority': authority.get('custody_authority') or '',
        'authority_source': authority.get('authority_source') or '',
        'reconciled': bool(authority.get('reconciled')),
    }


def workflow_blocked_read_only(shipment: Any | None) -> bool:
    """Delivery gate projection — read-only wrapper around pod_cod_policy."""
    if shipment is None:
        return False
    return pod_cod_policy.derive_delivery_blocked(shipment)
