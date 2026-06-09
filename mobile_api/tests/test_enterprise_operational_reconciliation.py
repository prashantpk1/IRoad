from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from mobile_api.tests.transaction_test_case import TransactionTestCase
from django.utils import timezone

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.services.execution_validation_service import (
    ExecutionValidationService,
)
from mobile_api.hard_pod.guards.immutable_custody_guard import (
    assert_custody_header_mutable,
)
from mobile_api.hard_pod.models import HardPODCustodySubmission, HardPODCustodySubmissionEvent
from mobile_api.hard_pod.services.hard_pod_execute_integration import (
    HardPodExecuteIntegrationService,
)
from mobile_api.hard_pod.services.hard_pod_custody_service import HardPodCustodyService
from mobile_api.issues.models.operational_issue import OperationalIssue
from mobile_api.issues.services.issue_lifecycle_service import IssueLifecycleService
from mobile_api.payment_collection.exceptions import PaymentCollectionError
from mobile_api.payment_collection.services.payment_collection_service import (
    PaymentCollectionService,
)
from mobile_api.services.operational_reconciliation_service import (
    OperationalReconciliationService,
)


def _driver(pk: str = 'drv-1') -> SimpleNamespace:
    return SimpleNamespace(pk=pk, driver_id=pk, driver_name='Driver')


def _shipment(pk: str = 'ship-1') -> SimpleNamespace:
    return SimpleNamespace(pk=pk, shipment_id=pk, tenant_schema='tenant_a')


class HardPodExecuteIntegrationTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant_schema = 'tenant_a'
        self.driver = _driver()
        self.shipment = _shipment()
        self.action = SimpleNamespace(
            action_code=f'HARD-POD-{uuid4().hex[:8]}',
            hard_copy_collection=True,
            status='Active',
        )
        self.action_log = SimpleNamespace(
            log_id=uuid4(),
            log_no=f'OAL-{uuid4().hex[:8]}',
            operation_action=self.action,
            log_date=timezone.now(),
        )
        self.submission = HardPODCustodySubmission.objects.create(
            tenant_schema=self.tenant_schema,
            driver_id=self.driver.pk,
            shipment_id=self.shipment.pk,
            client_submission_id='client-sub-1',
            receiver_name='Receiver',
        )
        HardPodCustodyService().record_verified(self.submission, actor_label='Receiver')

    def test_hard_pod_execute_requires_submission_reference(self) -> None:
        context = ExecuteActionContext(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            user_id='user-1',
            job_type='shipment',
            job_id=self.shipment.pk,
            action_code=self.action.action_code,
            payload={},
        )
        context.shipment = self.shipment
        context.operation_action = self.action

        with self.assertRaises(ExecuteActionError) as exc:
            HardPodExecuteIntegrationService().validate_execute_requirements(context)
        self.assertEqual(exc.exception.code, 'hard_pod_submission_required')

    def test_hard_pod_execute_validation_still_reaches_workflow_gate(self) -> None:
        context = ExecuteActionContext(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            user_id='user-1',
            job_type='shipment',
            job_id=self.shipment.pk,
            action_code=self.action.action_code,
            payload={},
        )
        context.shipment = self.shipment
        context.operation_action = self.action

        with self.assertRaises(ExecuteActionError) as exc:
            ExecutionValidationService().validate_pre_execute_after_idempotency(context)
        self.assertEqual(exc.exception.code, 'stale_workflow')

    def test_hard_pod_execute_links_submission_to_action_log(self) -> None:
        context = ExecuteActionContext(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            user_id='user-1',
            job_type='shipment',
            job_id=self.shipment.pk,
            action_code=self.action.action_code,
            payload={
                'client_submission_id': self.submission.client_submission_id,
            },
        )
        context.shipment = self.shipment
        context.operation_action = self.action

        linked = HardPodExecuteIntegrationService().bind_action_log(context, self.action_log)

        self.assertIsNotNone(linked)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.promotion_action_log_id, str(self.action_log.log_id))
        self.assertTrue(self.submission.promoted_at)

        with self.assertRaises(ValueError):
            self.submission.save(update_fields=['receiver_name'])


class IssueLifecycleTests(TransactionTestCase):
    def setUp(self) -> None:
        self.issue = OperationalIssue.objects.create(
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            driver_id='drv-1',
            client_issue_id=f'issue-{uuid4().hex[:8]}',
            issue_type=OperationalIssue.IssueType.ROUTE_BLOCKED,
            severity=OperationalIssue.Severity.CRITICAL,
            notes='Blocked route',
            blocking_recommended=True,
        )

    def test_supervisor_lifecycle_transitions_append_events(self) -> None:
        service = IssueLifecycleService()

        service.record_opened(self.issue, notes='Opened', auto_escalate=True)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.escalation_state, OperationalIssue.EscalationState.ESCALATED)

        service.acknowledge(self.issue, notes='Ack')
        service.resolve(self.issue, notes='Resolved')
        service.reopen(self.issue, notes='Reopened')
        service.reject(self.issue, notes='Rejected')

        self.issue.refresh_from_db()
        self.assertEqual(self.issue.escalation_state, OperationalIssue.EscalationState.REJECTED)
        self.assertIsNotNone(self.issue.resolved_at)
        self.assertGreaterEqual(self.issue.escalation_events.count(), 5)

    def test_lifecycle_preview_shows_append_only_events(self) -> None:
        service = IssueLifecycleService()
        service.record_opened(self.issue, notes='Opened', auto_escalate=False)
        service.resolve(self.issue, notes='Resolved')

        preview = service.build_timeline_preview(self.issue)
        kinds = [row['event_type'] for row in preview['timeline_preview']]
        self.assertIn('resolved', kinds)
        self.assertIn('opened', kinds)


class OperationalReconciliationTests(TransactionTestCase):
    def setUp(self) -> None:
        self.issue = OperationalIssue.objects.create(
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            driver_id='drv-1',
            client_issue_id=f'issue-{uuid4().hex[:8]}',
            issue_type=OperationalIssue.IssueType.DELAY,
            severity=OperationalIssue.Severity.HIGH,
            notes='Traffic delay',
            blocking_recommended=True,
        )
        IssueLifecycleService().record_opened(self.issue, notes='Opened', auto_escalate=True)

        self.submission = HardPODCustodySubmission.objects.create(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='ship-1',
            client_submission_id=f'client-sub-{uuid4().hex[:8]}',
            receiver_name='Receiver',
            promoted_at=timezone.now(),
            promotion_action_log_id=str(uuid4()),
        )
        HardPodCustodyService().record_verified(self.submission, actor_label='Receiver')

    def test_reconciliation_authority_and_timeline_overlays(self) -> None:
        context = SimpleNamespace(
            tenant_schema='tenant_a',
            driver=_driver(),
            shipment=_shipment(),
            job_id='ship-1',
            pod_cod={'treasury_pending': True},
            authoritative={'allowed_actions': []},
        )

        service = OperationalReconciliationService()
        result = service.reconcile(context=context)
        overlays = service.build_timeline_overlays(context=context)

        self.assertIn('custody_authority', result)
        self.assertTrue(result['issue_authority']['unresolved_issue_count'] >= 1)
        self.assertTrue(any(row.get('hard_pod_timeline_kind') == 'custody_promoted' for row in overlays))
        self.assertTrue(any(row.get('issue_timeline_kind') == 'issue_opened' for row in overlays))


class ImmutableCustodyGuardTests(TransactionTestCase):
    def test_promoted_submission_rejects_header_mutation(self) -> None:
        submission = HardPODCustodySubmission.objects.create(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='ship-1',
            client_submission_id=f'client-sub-{uuid4().hex[:8]}',
            promoted_at=timezone.now(),
            promotion_action_log_id=str(uuid4()),
        )

        submission.receiver_name = 'Updated'
        with self.assertRaises(ValueError):
            assert_custody_header_mutable(submission, update_fields=['receiver_name'])


class PaymentReplayMappingTests(TransactionTestCase):
    def test_replay_integrity_mismatch_maps_to_409(self) -> None:
        class ReplayEvidenceRows:
            def order_by(self, *_args: object, **_kwargs: object) -> list[object]:
                return []

        class ReplayIdempotency:
            def get_by_client_payment(self, **_kwargs: object) -> object:
                return SimpleNamespace(
                    expected_amount='10.00',
                    amount='10.00',
                    evidence_rows=ReplayEvidenceRows(),
                )

            def assert_replay_scope(self, **_kwargs: object) -> None:
                raise ValueError('payment_replay_integrity_mismatch')

        service = PaymentCollectionService(
            idempotency=ReplayIdempotency(),
            validation=SimpleNamespace(),
            reconciliation=SimpleNamespace(compute_variance=lambda **_kwargs: {}),
            bundle_service=SimpleNamespace(),
            response_builder=SimpleNamespace(),
        )

        payload = {
            'client_payment_id': 'pay-1',
            'shipment_id': 'ship-1',
            'amount': '10.00',
            'notes': '',
            'payment_mode': 'cash',
            'proof_media': [],
        }

        with self.assertRaises(PaymentCollectionError) as exc:
            service.stage_payment(driver=_driver(), tenant_schema='tenant_a', payload=payload)

        self.assertEqual(exc.exception.code, 'payment_replay_integrity_mismatch')
        self.assertEqual(exc.exception.http_status, 409)


class OperationalReconciliationAlertTests(TransactionTestCase):
    def test_no_custody_alert_during_in_transit(self) -> None:
        shipment = SimpleNamespace(
            pk='ship-1',
            shipment_id='ship-1',
            pod_type='Hard',
            shipment_status='In Transit',
            driver_id='drv-1',
            driver=SimpleNamespace(pk='drv-1'),
        )
        context = SimpleNamespace(
            shipment=shipment,
            tenant_schema='tenant_a',
            reconciliation={
                'pod_cod': {
                    'log_evidence': {},
                },
            },
        )
        service = OperationalReconciliationService()
        alerts = service._build_alerts(
            context,
            authority={'reconciled': False},
            issues={'unresolved_issue_count': 0, 'blocking_recommendation': False},
        )
        self.assertFalse(any(row.get('code') == 'custody_unreconciled' for row in alerts))
