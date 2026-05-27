"""
mobile_api/issues/services/issue_escalation_service.py

Append-only escalation evidence and initial escalation state for new issues.
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from mobile_api.issues.models.operational_issue import (
    OperationalIssue,
    OperationalIssueEscalationEvent,
    OperationalIssueTimelineEntry,
)
from mobile_api.issues.services.issue_lifecycle_service import IssueLifecycleService


class IssueEscalationService:
    """Record escalation lifecycle events and timeline preview rows."""

    EVENT_REPORTED = 'issue_reported'
    EVENT_AUTO_ESCALATED = 'auto_escalated'

    def __init__(self, *, lifecycle_service: IssueLifecycleService | None = None) -> None:
        self._lifecycle = lifecycle_service or IssueLifecycleService()

    def record_initial_report(
        self,
        issue: OperationalIssue,
        *,
        notes: str = '',
        auto_escalate: bool = False,
    ) -> tuple[OperationalIssueEscalationEvent, OperationalIssueTimelineEntry]:
        """
        Create open-state escalation evidence + timeline entry for a new issue.

        Optionally transitions to ``escalated`` when severity/type warrants it.
        """
        open_event, timeline = self._lifecycle.record_opened(
            issue,
            notes=notes,
            auto_escalate=auto_escalate,
        )
        return open_event, timeline

    def build_escalation_payload(
        self,
        issue: OperationalIssue,
        *,
        latest_event: OperationalIssueEscalationEvent | None = None,
    ) -> dict[str, Any]:
        if latest_event is None:
            latest_event = (
                issue.escalation_events.order_by('-recorded_at').first()
            )
        return {
            'issue_id': str(issue.pk),
            'escalation_state': (issue.escalation_state or '').strip(),
            'latest_event_type': getattr(latest_event, 'event_type', '') or '',
            'latest_to_state': getattr(latest_event, 'to_state', '') or '',
            'recorded_at': (
                latest_event.recorded_at.isoformat()
                if latest_event and latest_event.recorded_at
                else None
            ),
            'event_count': issue.escalation_events.count(),
        }

    def build_timeline_preview(
        self,
        issue: OperationalIssue,
        *,
        limit: int = 5,
    ) -> dict[str, Any]:
        return self._lifecycle.build_timeline_preview(issue, limit=limit)

    def acknowledge(self, issue: OperationalIssue, *, notes: str = '') -> IssueLifecycleEvent:
        return self._lifecycle.acknowledge(issue, notes=notes)

    def resolve(self, issue: OperationalIssue, *, notes: str = '') -> IssueLifecycleEvent:
        return self._lifecycle.resolve(issue, notes=notes)

    def reject(self, issue: OperationalIssue, *, notes: str = '') -> IssueLifecycleEvent:
        return self._lifecycle.reject(issue, notes=notes)

    def reopen(self, issue: OperationalIssue, *, notes: str = '') -> IssueLifecycleEvent:
        return self._lifecycle.reopen(issue, notes=notes)

from mobile_api.issues.models.operational_issue import IssueLifecycleEvent
