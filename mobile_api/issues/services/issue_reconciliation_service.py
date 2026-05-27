"""
mobile_api/issues/services/issue_reconciliation_service.py

Reconcile operational exceptions with workflow impact projections (read-only).
"""
from __future__ import annotations

from typing import Any

from mobile_api.issues.models.operational_issue import OperationalIssue


# Issue types that typically warrant supervisor attention / execute-time gates.
_HIGH_IMPACT_TYPES = frozenset(
    {
        OperationalIssue.IssueType.ACCIDENT,
        OperationalIssue.IssueType.ROUTE_BLOCKED,
        OperationalIssue.IssueType.VEHICLE_BREAKDOWN,
        OperationalIssue.IssueType.PAYMENT_DISPUTE,
    }
)


class IssueReconciliationService:
    """
    Compute advisory workflow impact — does NOT mutate shipment or workflow state.
    """

    def compute_blocking_recommended(
        self,
        *,
        issue_type: str,
        severity: str,
    ) -> bool:
        issue_type = (issue_type or '').strip().casefold()
        severity = (severity or '').strip().casefold()

        if issue_type in _HIGH_IMPACT_TYPES:
            return True
        if severity in {
            OperationalIssue.Severity.HIGH,
            OperationalIssue.Severity.CRITICAL,
        }:
            return True
        if issue_type == OperationalIssue.IssueType.DELAY and severity in {
            OperationalIssue.Severity.MEDIUM,
            OperationalIssue.Severity.HIGH,
            OperationalIssue.Severity.CRITICAL,
        }:
            return True
        return False

    def count_unresolved_for_shipment(
        self,
        *,
        tenant_schema: str,
        shipment_id: str,
        exclude_issue_id: str | None = None,
    ) -> int:
        qs = OperationalIssue.objects.filter(
            tenant_schema=(tenant_schema or '').strip(),
            shipment_id=(shipment_id or '').strip(),
        ).exclude(
            escalation_state__in=[
                OperationalIssue.EscalationState.RESOLVED,
                OperationalIssue.EscalationState.REJECTED,
            ],
        )
        if exclude_issue_id:
            qs = qs.exclude(pk=exclude_issue_id)
        return qs.count()

    def workflow_impact(
        self,
        *,
        issue: OperationalIssue,
        unresolved_count: int | None = None,
    ) -> dict[str, Any]:
        if unresolved_count is None:
            unresolved_count = self.count_unresolved_for_shipment(
                tenant_schema=issue.tenant_schema,
                shipment_id=issue.shipment_id,
                exclude_issue_id=None,
            )
        blocking = bool(issue.blocking_recommended)
        return {
            'blocking_recommended': blocking,
            'unresolved_issue_count': int(unresolved_count),
            'has_unresolved_issues': int(unresolved_count) > 0,
            'workflow_mutation_performed': False,
            'execute_action_required_for_progression': blocking,
        }
