"""
mobile_api/services/operational_reconciliation_service.py

Unified operational reconciliation across custody, issues, treasury, and workflow overlays.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.hard_pod.models import HardPODCustodySubmission, HardPODCustodySubmissionEvent
from mobile_api.hard_pod.services.custody_authority_service import HardPodCustodyAuthorityService
from mobile_api.issues.models.operational_issue import OperationalIssue, OperationalIssueEscalationEvent
from tenant_workspace.models import TenantShipment
from mobile_api.job_detail.timeline.timeline_event_mapper import map_escalation_events_to_timeline
from mobile_api.payment_collection.services.payment_reconciliation_service import PaymentReconciliationService


class OperationalReconciliationService:
    """Produce canonical reconciliation slices and overlay timeline events."""

    def __init__(self) -> None:
        self._custody_authority = HardPodCustodyAuthorityService()
        self._payments = PaymentReconciliationService()

    def reconcile(self, *, context: Any, request: Any | None = None) -> dict[str, Any]:
        _ = request
        shipment = getattr(context, 'shipment', None)
        tenant_schema = (getattr(context, 'tenant_schema', None) or '').strip()
        shipment_id = str(
            getattr(shipment, 'pk', None)
            or getattr(shipment, 'shipment_id', None)
            or getattr(context, 'job_id', '')
            or ''
        ).strip()
        driver = getattr(context, 'driver', None)
        driver_id = str(getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or '').strip()
        authority = self._custody_authority.resolve_authority(
            tenant_schema=tenant_schema,
            shipment_id=shipment_id,
            driver_id=driver_id,
            action_log_id=str(getattr(context, 'latest_action_log_id', '') or '').strip(),
        )
        issues = self._issue_authority(context)

        return {
            'workflow_authority': dict(getattr(context, 'authoritative', None) or {}),
            'custody_authority': authority,
            'treasury_authority': self._treasury_authority(context),
            'issue_authority': issues,
            'reconciliation_alerts': self._build_alerts(context, authority=authority, issues=issues),
        }

    def build_timeline_overlays(self, *, context: Any, request: Any | None = None) -> list[dict[str, Any]]:
        _ = request
        shipment = getattr(context, 'shipment', None)
        if shipment is None:
            return []

        shipment_id = str(getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', '') or '').strip()
        tenant_schema = (getattr(context, 'tenant_schema', None) or '').strip()
        issue_events = self._issue_events(tenant_schema=tenant_schema, shipment_id=shipment_id, request=request)
        custody_events = self._custody_events(
            tenant_schema=tenant_schema,
            shipment_id=shipment_id,
            driver_id=str(getattr(getattr(context, 'driver', None), 'pk', None) or getattr(getattr(context, 'driver', None), 'driver_id', '') or '').strip(),
        )
        return self._merge_events(issue_events + custody_events)

    def _issue_authority(self, context: Any) -> dict[str, Any]:
        shipment = getattr(context, 'shipment', None)
        if shipment is None:
            return {
                'unresolved_issue_count': 0,
                'has_unresolved_issues': False,
                'blocking_recommendation': False,
            }
        tenant_schema = (getattr(context, 'tenant_schema', None) or '').strip()
        shipment_id = str(getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', '') or '').strip()
        unresolved = OperationalIssue.objects.filter(
            tenant_schema=tenant_schema,
            shipment_id=shipment_id,
        ).exclude(
            escalation_state__in=[OperationalIssue.EscalationState.RESOLVED, OperationalIssue.EscalationState.REJECTED],
        )
        return {
            'unresolved_issue_count': unresolved.count(),
            'has_unresolved_issues': unresolved.exists(),
            'blocking_recommendation': unresolved.filter(blocking_recommended=True).exists(),
        }

    def _treasury_authority(self, context: Any) -> dict[str, Any]:
        pod_cod = dict(getattr(context, 'pod_cod', None) or {})
        payment_bundle = dict(pod_cod.get('payment_bundle') or {})
        return {
            'payment_bundle_id': payment_bundle.get('bundle_id'),
            'treasury_pending': bool(pod_cod.get('treasury_pending', False)),
            'variance_detected': bool(payment_bundle.get('variance_detected', False)),
            'reconciled': not bool(pod_cod.get('treasury_pending', False)),
        }

    def _build_alerts(
        self,
        context: Any,
        *,
        authority: dict[str, Any],
        issues: dict[str, Any],
    ) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        if self._should_surface_custody_unreconciled_alert(context, authority):
            alerts.append(
                {
                    'code': 'custody_unreconciled',
                    'severity': 'warning',
                    'message_key': 'mobile.hard_pod.custody_unreconciled',
                }
            )
        if issues.get('blocking_recommendation'):
            alerts.append(
                {
                    'code': 'issue_blocking_recommendation',
                    'severity': 'warning',
                    'message_key': 'mobile.issues.blocking_recommended_advisory',
                }
            )
        if issues.get('unresolved_issue_count'):
            alerts.append(
                {
                    'code': 'unresolved_issues',
                    'severity': 'info',
                    'message_key': 'mobile.issues.unresolved_warning',
                    'count': int(issues.get('unresolved_issue_count') or 0),
                }
            )
        return alerts

    def _should_surface_custody_unreconciled_alert(
        self,
        context: Any,
        authority: dict[str, Any],
    ) -> bool:
        """
        Hard-copy custody warnings belong on the POD step — not pickup/in transit.

        ``reconciled=False`` is normal before digital POD; only warn when hard-copy
        custody is actually outstanding (after digital POD at delivery).
        """
        if authority.get('reconciled'):
            return False
        shipment = getattr(context, 'shipment', None)
        if shipment is None:
            return False
        pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
        if pod_type != TenantShipment.PodType.HARD.casefold():
            return False
        pod_bundle = dict((getattr(context, 'reconciliation', None) or {}).get('pod_cod') or {})
        evidence = dict(pod_bundle.get('log_evidence') or {})
        tenant_schema = (getattr(context, 'tenant_schema', None) or '').strip()
        return pod_cod_policy.derive_hard_pod_pending(
            shipment,
            log_evidence=evidence,
            tenant_schema=tenant_schema,
        )

    def _issue_events(self, *, tenant_schema: str, shipment_id: str, request: Any | None = None) -> list[dict[str, Any]]:
        if not (tenant_schema and shipment_id):
            return []
        issues = list(
            OperationalIssue.objects.filter(
                tenant_schema=tenant_schema,
                shipment_id=shipment_id,
            ).order_by('-created_at')
        )
        if not issues:
            return []
        events = list(
            OperationalIssueEscalationEvent.objects.filter(
                issue_id__in=[issue.pk for issue in issues],
            ).select_related('issue').order_by('-recorded_at')
        )
        issues_by_id = {str(issue.pk): issue for issue in issues}
        return map_escalation_events_to_timeline(events, issues_by_id=issues_by_id, request=request)

    def _custody_events(self, *, tenant_schema: str, shipment_id: str, driver_id: str) -> list[dict[str, Any]]:
        if not (tenant_schema and shipment_id):
            return []

        submissions = list(
            HardPODCustodySubmission.objects.filter(
                tenant_schema=tenant_schema,
                shipment_id=shipment_id,
            ).order_by('-promoted_at', '-submitted_at', '-created_at')
        )
        if driver_id:
            submissions = [row for row in submissions if (row.driver_id or '').strip() == driver_id]
        if not submissions:
            return []

        rows: list[dict[str, Any]] = []
        for submission in submissions:
            submitted_at = submission.submitted_at.isoformat() if submission.submitted_at else ''
            rows.append(
                {
                    'event_id': f'{submission.pk}:submitted',
                    'log_id': '',
                    'log_date': submitted_at,
                    'created_at': submitted_at,
                    'event_type': 'hard_pod',
                    'action_code': 'HARD_POD_SUBMITTED',
                    'action_label': 'Hard POD submitted',
                    'source': 'Mobile',
                    'source_channel': 'hard_pod',
                    'notes': '',
                    'status_impact': None,
                    'shipment_id': submission.shipment_id,
                    'movement_id': None,
                    'latitude': submission.latitude,
                    'longitude': submission.longitude,
                    'is_reversal': False,
                    'append_only': True,
                    'authority': 'hard_pod',
                    'hard_pod_timeline_kind': 'custody_submitted',
                    'submission_id': str(submission.pk),
                }
            )
            for event in submission.custody_events.order_by('occurred_at', 'created_at'):
                timestamp = event.occurred_at.isoformat() if event.occurred_at else ''
                event_type = (event.event_type or '').strip()
                event_label = event_type.replace('_', ' ')
                rows.append(
                    {
                        'event_id': str(event.pk),
                        'log_id': '',
                        'log_date': timestamp,
                        'created_at': timestamp,
                        'event_type': 'hard_pod',
                        'action_code': f'HARD_POD_{event_type.upper()}',
                        'action_label': f'Hard POD {event_label}',
                        'source': 'Mobile',
                        'source_channel': 'hard_pod',
                        'notes': (event.notes or '').strip(),
                        'status_impact': None,
                        'shipment_id': event.shipment_id,
                        'movement_id': None,
                        'latitude': event.latitude,
                        'longitude': event.longitude,
                        'is_reversal': False,
                        'append_only': True,
                        'authority': 'hard_pod',
                        'hard_pod_timeline_kind': event.event_type,
                        'submission_id': str(submission.pk),
                    }
                )
            if submission.promoted_at:
                promoted_at = submission.promoted_at.isoformat()
                rows.append(
                    {
                        'event_id': f'{submission.pk}:promoted',
                        'log_id': '',
                        'log_date': promoted_at,
                        'created_at': promoted_at,
                        'event_type': 'hard_pod',
                        'action_code': 'HARD_POD_PROMOTED',
                        'action_label': 'Hard POD promoted',
                        'source': 'Execute Action',
                        'source_channel': 'hard_pod_execute',
                        'notes': '',
                        'status_impact': None,
                        'shipment_id': submission.shipment_id,
                        'movement_id': None,
                        'latitude': submission.latitude,
                        'longitude': submission.longitude,
                        'is_reversal': False,
                        'append_only': True,
                        'authority': 'action_log',
                        'hard_pod_timeline_kind': 'custody_promoted',
                        'submission_id': str(submission.pk),
                        'action_log_id': submission.promotion_action_log_id or '',
                    }
                )
        return rows

    @staticmethod
    def _merge_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        combined = list(events)
        combined.sort(
            key=lambda row: (
                str(row.get('created_at') or row.get('log_date') or ''),
                str(row.get('event_id') or row.get('log_id') or ''),
            ),
            reverse=True,
        )
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in combined:
            token = str(row.get('event_id') or row.get('log_id') or '').strip()
            if token and token in seen:
                continue
            if token:
                seen.add(token)
            out.append(row)
        return out
