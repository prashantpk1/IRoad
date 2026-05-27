"""
mobile_api/issues/services/issue_lifecycle_service.py

Append-only issue lifecycle orchestration (open, acknowledge, resolve, reject, reopen).
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from mobile_api.issues.models.operational_issue import (
    IssueLifecycleEvent,
    OperationalIssue,
    OperationalIssueTimelineEntry,
)


class IssueLifecycleService:
    """Supervisor-facing lifecycle transitions for operational issues."""

    EVENT_OPENED = 'opened'
    EVENT_ESCALATED = 'escalated'
    EVENT_ACKNOWLEDGED = 'acknowledged'
    EVENT_RESOLVED = 'resolved'
    EVENT_REJECTED = 'rejected'
    EVENT_REOPENED = 'reopened'

    def record_opened(
        self,
        issue: OperationalIssue,
        *,
        notes: str = '',
        auto_escalate: bool = False,
    ) -> tuple[IssueLifecycleEvent, OperationalIssueTimelineEntry]:
        event = self._transition(
            issue,
            from_state='',
            to_state=OperationalIssue.EscalationState.OPEN,
            event_type=self.EVENT_OPENED,
            notes=notes or issue.notes or '',
        )
        timeline = self._create_timeline_entry(
            issue,
            event_type=self.EVENT_OPENED,
            title=self._title_for_issue(issue),
            summary=(notes or issue.notes or '').strip(),
        )
        if auto_escalate:
            self._transition(
                issue,
                from_state=OperationalIssue.EscalationState.OPEN,
                to_state=OperationalIssue.EscalationState.ESCALATED,
                event_type=self.EVENT_ESCALATED,
                notes='Auto-escalated based on severity/type policy.',
            )
        return event, timeline

    def acknowledge(
        self,
        issue: OperationalIssue,
        *,
        notes: str = '',
    ) -> IssueLifecycleEvent:
        return self._transition(
            issue,
            from_state=issue.escalation_state,
            to_state=OperationalIssue.EscalationState.ACKNOWLEDGED,
            event_type=self.EVENT_ACKNOWLEDGED,
            notes=notes or issue.notes or '',
        )

    def resolve(
        self,
        issue: OperationalIssue,
        *,
        notes: str = '',
    ) -> IssueLifecycleEvent:
        issue.resolved_at = timezone.now()
        issue.save(update_fields=['escalation_state', 'resolved_at'])
        return self._transition(
            issue,
            from_state=issue.escalation_state,
            to_state=OperationalIssue.EscalationState.RESOLVED,
            event_type=self.EVENT_RESOLVED,
            notes=notes or issue.notes or '',
        )

    def reject(
        self,
        issue: OperationalIssue,
        *,
        notes: str = '',
    ) -> IssueLifecycleEvent:
        issue.resolved_at = timezone.now()
        issue.save(update_fields=['escalation_state', 'resolved_at'])
        return self._transition(
            issue,
            from_state=issue.escalation_state,
            to_state=OperationalIssue.EscalationState.REJECTED,
            event_type=self.EVENT_REJECTED,
            notes=notes or issue.notes or '',
        )

    def reopen(
        self,
        issue: OperationalIssue,
        *,
        notes: str = '',
    ) -> IssueLifecycleEvent:
        issue.resolved_at = None
        issue.save(update_fields=['escalation_state', 'resolved_at'])
        return self._transition(
            issue,
            from_state=issue.escalation_state,
            to_state=OperationalIssue.EscalationState.OPEN,
            event_type=self.EVENT_REOPENED,
            notes=notes or issue.notes or '',
        )

    def build_timeline_preview(
        self,
        issue: OperationalIssue,
        *,
        limit: int = 5,
    ) -> dict[str, Any]:
        rows = list(
            issue.escalation_events.order_by('-recorded_at', '-id')[:limit]
        )
        return {
            'scope': 'shipment',
            'shipment_id': issue.shipment_id,
            'timeline_preview': [
                {
                    'event_id': str(row.pk),
                    'event_category': 'issue',
                    'event_type': row.event_type,
                    'title': f"{(issue.issue_type or 'issue').replace('_', ' ').title()} {row.to_state or 'updated'}",
                    'summary': row.notes,
                    'severity': issue.severity,
                    'escalation_state': row.to_state,
                    'recorded_at': row.recorded_at.isoformat() if row.recorded_at else None,
                }
                for row in rows
            ],
            'has_more': issue.escalation_events.count() > len(rows),
        }

    def build_issue_authority(self, issue: OperationalIssue) -> dict[str, Any]:
        return {
            'issue_id': str(issue.pk),
            'issue_state': (issue.escalation_state or '').strip(),
            'unresolved': issue.is_unresolved,
            'resolved_at': issue.resolved_at.isoformat() if issue.resolved_at else None,
        }

    def _transition(
        self,
        issue: OperationalIssue,
        *,
        from_state: str,
        to_state: str,
        event_type: str,
        notes: str,
    ) -> IssueLifecycleEvent:
        issue.escalation_state = to_state
        if to_state not in {
            OperationalIssue.EscalationState.RESOLVED,
            OperationalIssue.EscalationState.REJECTED,
        }:
            issue.resolved_at = None
            issue.save(update_fields=['escalation_state', 'resolved_at'])
        else:
            issue.save(update_fields=['escalation_state', 'resolved_at'])

        return IssueLifecycleEvent.objects.create(
            issue=issue,
            tenant_schema=issue.tenant_schema,
            shipment_id=issue.shipment_id,
            driver_id=issue.driver_id,
            from_state=from_state,
            to_state=to_state,
            event_type=event_type,
            notes=(notes or '')[:2000],
        )

    @staticmethod
    def _create_timeline_entry(
        issue: OperationalIssue,
        *,
        event_type: str,
        title: str,
        summary: str,
    ) -> OperationalIssueTimelineEntry:
        return OperationalIssueTimelineEntry.objects.create(
            issue=issue,
            tenant_schema=issue.tenant_schema,
            shipment_id=issue.shipment_id,
            driver_id=issue.driver_id,
            event_category='issue',
            event_type=event_type,
            title=title[:200],
            summary=(summary or '')[:4000],
            severity=issue.severity,
            escalation_state=issue.escalation_state,
            recorded_at=timezone.now(),
        )

    @staticmethod
    def _title_for_issue(issue: OperationalIssue) -> str:
        label = (issue.issue_type or 'issue').replace('_', ' ').title()
        return f'{label} reported'
