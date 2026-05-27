"""
Operational issue visibility in Job Detail timeline and execution warnings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import TransactionTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
)
from mobile_api.issues.models.operational_issue import (
    OperationalIssue,
    OperationalIssueEscalationEvent,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.job_detail_projection_builder import (
    apply_operational_issues_visibility,
    build_operational_issues_visibility,
    enrich_timeline_with_operational_issues,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    ISSUE_TIMELINE_ESCALATED,
    ISSUE_TIMELINE_OPENED,
    ISSUE_TIMELINE_RESOLVED,
    classify_issue_escalation_milestone,
    map_escalation_event_to_timeline,
    merge_issue_events_into_timeline,
)
from mobile_api.execution.services.execution_validation_service import (
    ExecutionValidationService,
)


class OperationalIssuesIntegrationTests(TransactionTestCase):
    def _issue(self, *, shipment_id: str, state: str = 'open', blocking: bool = True):
        issue = OperationalIssue.objects.create(
            tenant_schema='tenant_ops',
            shipment_id=shipment_id,
            driver_id='drv-1',
            client_issue_id=f'issue-{uuid.uuid4()}',
            issue_type='delay',
            severity='high',
            notes='Heavy traffic',
            escalation_state=state,
            blocking_recommended=blocking,
        )
        OperationalIssueEscalationEvent.objects.create(
            issue=issue,
            tenant_schema=issue.tenant_schema,
            shipment_id=issue.shipment_id,
            driver_id=issue.driver_id,
            from_state='',
            to_state='open',
            event_type='issue_reported',
            notes='Reported',
            recorded_at=datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc),
        )
        if state == 'escalated':
            OperationalIssueEscalationEvent.objects.create(
                issue=issue,
                tenant_schema=issue.tenant_schema,
                shipment_id=issue.shipment_id,
                driver_id=issue.driver_id,
                from_state='open',
                to_state='escalated',
                event_type='auto_escalated',
                notes='Escalated',
                recorded_at=datetime(2026, 5, 27, 11, 0, tzinfo=timezone.utc),
            )
        return issue

    def test_issue_timeline_milestone_classification(self):
        self.assertEqual(
            classify_issue_escalation_milestone(to_state='open', event_type='issue_reported'),
            ISSUE_TIMELINE_OPENED,
        )
        self.assertEqual(
            classify_issue_escalation_milestone(to_state='escalated', event_type='auto_escalated'),
            ISSUE_TIMELINE_ESCALATED,
        )

    def test_merge_issue_events_into_action_log_timeline(self):
        action_events = [
            {
                'log_id': 'log-1',
                'created_at': '2026-05-27T09:00:00+00:00',
                'event_type': 'action',
            }
        ]
        issue = self._issue(shipment_id=str(uuid.uuid4()), state='escalated')
        esc = issue.escalation_events.order_by('-recorded_at').first()
        issue_event = map_escalation_event_to_timeline(esc, issue=issue)
        merged = merge_issue_events_into_timeline(action_events, [issue_event])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]['issue_timeline_kind'], ISSUE_TIMELINE_ESCALATED)

    def test_job_detail_operational_issues_visibility(self):
        shipment_id = str(uuid.uuid4())
        self._issue(shipment_id=shipment_id, state='open', blocking=True)

        ctx = JobDetailContext(
            driver=SimpleNamespace(pk='drv-1', driver_id='drv-1'),
            tenant_schema='tenant_ops',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
        )
        visibility = build_operational_issues_visibility(ctx)
        self.assertEqual(visibility['unresolved_issue_count'], 1)
        self.assertTrue(visibility['blocking_recommendation'])
        self.assertEqual(len(visibility['operational_issues']), 1)

    def test_enrich_timeline_with_operational_issues(self):
        shipment_id = str(uuid.uuid4())
        self._issue(shipment_id=shipment_id, state='escalated')

        ctx = JobDetailContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_ops',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
        )
        bundle = enrich_timeline_with_operational_issues(
            {'timeline_preview': [], 'scope': 'shipment'},
            ctx,
        )
        self.assertTrue(bundle.get('includes_operational_issues'))
        kinds = {row.get('issue_timeline_kind') for row in bundle['timeline_preview']}
        self.assertIn(ISSUE_TIMELINE_OPENED, kinds)
        self.assertIn(ISSUE_TIMELINE_ESCALATED, kinds)

    def test_unresolved_issue_warnings_on_execute(self):
        shipment_id = str(uuid.uuid4())
        self._issue(shipment_id=shipment_id, blocking=True)

        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_ops',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            action_code='A2',
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
            operation_action=MagicMock(action_code='A2', english_label='Start'),
            payload={'latitude': '1', 'longitude': '2', 'notes': 'ok'},
        )

        with self.mock_action_requirements():
            EvidenceValidationService().validate_required_evidence(ctx)

        self.assertEqual(ctx.alerts.get('unresolved_issue_count'), 1)
        self.assertTrue(ctx.alerts.get('blocking_recommendation'))
        overlay = ctx.alerts.get('execution_warning_overlay') or {}
        self.assertTrue(overlay.get('has_warnings'))
        self.assertFalse(overlay.get('hard_block'))

    def mock_action_requirements(self):
        from contextlib import contextmanager
        from unittest.mock import patch

        @contextmanager
        def _cm():
            with patch(
                'mobile_api.execution.evidence.evidence_validation_service.build_execution_requirements',
                return_value={
                    'gps': False,
                    'photo': False,
                    'photo_min_count': 0,
                    'video': False,
                    'video_min_count': 0,
                    'note': False,
                    'signature': False,
                },
            ), patch.object(
                EvidenceValidationService,
                '_media_security',
                create=True,
            ):
                svc = EvidenceValidationService()
                svc._media_security.validate_media = lambda ctx: None  # type: ignore[method-assign]
                yield

        return _cm()

    def test_issue_resolved_timeline_milestone(self):
        shipment_id = str(uuid.uuid4())
        issue = self._issue(shipment_id=shipment_id, state='open')
        OperationalIssueEscalationEvent.objects.create(
            issue=issue,
            tenant_schema=issue.tenant_schema,
            shipment_id=issue.shipment_id,
            driver_id=issue.driver_id,
            from_state='open',
            to_state='resolved',
            event_type='issue_resolved',
            notes='Resolved',
            recorded_at=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        )
        esc = issue.escalation_events.filter(to_state='resolved').first()
        event = map_escalation_event_to_timeline(esc, issue=issue)
        self.assertEqual(event['issue_timeline_kind'], ISSUE_TIMELINE_RESOLVED)
        self.assertIn('resolved', event['action_label'].casefold())

    def test_execution_validation_attaches_warnings_without_block(self):
        shipment_id = str(uuid.uuid4())
        self._issue(shipment_id=shipment_id, state='escalated', blocking=True)

        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_ops',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            action_code='A2',
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
        )
        ExecutionValidationService._attach_operational_issue_warnings(ctx)
        self.assertGreaterEqual(ctx.alerts.get('unresolved_issue_count', 0), 1)
        self.assertFalse((ctx.alerts.get('execution_warning_overlay') or {}).get('hard_block'))
        self.assertTrue(ctx.alerts.get('escalation_alerts'))

    def test_resolved_issue_not_counted_unresolved(self):
        shipment_id = str(uuid.uuid4())
        issue = self._issue(shipment_id=shipment_id, state='open')
        issue.escalation_state = OperationalIssue.EscalationState.RESOLVED
        issue.resolved_at = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)
        issue.save(update_fields=['escalation_state', 'resolved_at'])

        ctx = JobDetailContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_ops',
            user_id='u1',
            job_type='shipment',
            job_id=shipment_id,
            shipment=SimpleNamespace(pk=shipment_id, shipment_id=shipment_id),
        )
        apply_operational_issues_visibility(ctx)
        visibility = ctx.resolver_meta['operational_issues_visibility']
        self.assertEqual(visibility['unresolved_issue_count'], 0)
