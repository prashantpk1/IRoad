"""
Hard POD pending list — projection, reconciliation, and security tests.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from mobile_api.tests.transaction_test_case import TransactionTestCase
from django.utils import timezone

from mobile_api.hard_pod.projections.hard_pod_projection_builder import (
    CUSTODY_COLLECTED,
    CUSTODY_NOT_STARTED,
    CUSTODY_VERIFIED,
    VERIFICATION_VERIFIED,
    derive_custody_state,
)
from mobile_api.hard_pod.services.hard_pod_projection_service import (
    HardPodProjectionService,
    is_pending_hard_pod_queue_row,
)
from mobile_api.hard_pod.services.hard_pod_reconciliation_service import (
    reconcile_hard_pod_row,
)
from mobile_api.hard_pod.services.hard_pod_list_service import HardPodListService
from mobile_api.pod_capture.models import (
    PODCaptureBundle,
)
from mobile_api.hard_pod.models import (
    HardPODCustodySubmission,
    HardPODCustodySubmissionEvent,
)
from tenant_workspace.models import TenantShipment


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid.uuid4()
    d.driver_id = d.pk
    d.driver_status = 'Active'
    return d


def _shipment(
    *,
    pk=None,
    driver_id=None,
    pod_status=TenantShipment.PodStatus.PENDING,
    pod_type=TenantShipment.PodType.HARD,
    status=TenantShipment.ShipmentStatus.LOADED,
):
    s = MagicMock()
    s.pk = pk or uuid.uuid4()
    s.shipment_id = s.pk
    s.shipment_no = 'SH-HARD-001'
    s.driver_id = driver_id
    s.pod_status = pod_status
    s.pod_type = pod_type
    s.shipment_status = status
    s.order_type = ''
    s.collection_status = TenantShipment.CollectionStatus.PENDING
    s.booking = None
    return s


class HardPodProjectionBuilderTests(SimpleTestCase):
    def test_custody_state_verified_when_verification_row(self):
        state = derive_custody_state([], has_verification=True)
        self.assertEqual(state, CUSTODY_VERIFIED)

    def test_custody_state_collected_from_events(self):
        event = SimpleNamespace(event_type=HardPODCustodySubmissionEvent.EventType.COLLECTED)
        state = derive_custody_state([event], has_verification=False)
        self.assertEqual(state, CUSTODY_COLLECTED)

    def test_pending_queue_includes_hard_pod_pending(self):
        self.assertTrue(
            is_pending_hard_pod_queue_row(
                hard_pod_pending=True,
                custody_state=CUSTODY_NOT_STARTED,
                verification_state='pending',
            )
        )

    def test_pending_queue_excludes_verified_complete(self):
        self.assertFalse(
            is_pending_hard_pod_queue_row(
                hard_pod_pending=False,
                custody_state=CUSTODY_VERIFIED,
                verification_state=VERIFICATION_VERIFIED,
            )
        )


class HardPodReconciliationTests(TestCase):
    def test_missing_hard_pod_log_when_custody_without_log(self):
        shipment = _shipment()
        flags = reconcile_hard_pod_row(
            shipment=shipment,
            column_flags={'hard_pod_pending': True},
            log_evidence={'hard_pod_log': False},
            custody_state=CUSTODY_COLLECTED,
            verification_state='pending',
            portal_pod={},
        )
        self.assertTrue(flags['missing_hard_pod_log'])

    def test_custody_vs_workflow_mismatch_when_log_but_pending(self):
        shipment = _shipment()
        flags = reconcile_hard_pod_row(
            shipment=shipment,
            column_flags={'hard_pod_pending': True},
            log_evidence={'hard_pod_log': True},
            custody_state=CUSTODY_COLLECTED,
            verification_state='pending',
            portal_pod={},
        )
        self.assertTrue(flags['custody_vs_workflow_mismatch'])


class HardPodProjectionServiceTests(TestCase):
    @patch('mobile_api.hard_pod.services.hard_pod_projection_service.pod_cod_policy')
    @patch('mobile_api.hard_pod.services.hard_pod_projection_service.log_evidence_flags')
    def test_build_row_shape(self, mock_evidence, mock_policy):
        mock_policy.derive_pod_cod_flags.return_value = {
            'hard_pod_pending': True,
            'delivery_blocked': False,
        }
        mock_policy.derive_delivery_blocked.return_value = False
        mock_evidence.return_value = {'hard_pod_log': False}

        shipment = _shipment()
        row = HardPodProjectionService().build_row(
            shipment,
            driver=_driver(shipment.driver_id),
            tenant_schema='tenant_a',
            logs=[],
            custody_bundle={'events': [], 'receipt': None, 'verification': None},
        )
        self.assertEqual(row['shipment_id'], str(shipment.pk))
        self.assertTrue(row['hard_pod_pending'])
        self.assertIn('reconciliation', row)
        self.assertIn('custody_vs_workflow_mismatch', row['reconciliation'])


class HardPodOwnershipFilterTests(SimpleTestCase):
    def test_driver_may_not_view_other_driver_shipment(self):
        owner = _driver()
        other = _driver()
        shipment = _shipment(driver_id=other.pk)
        self.assertFalse(
            HardPodProjectionService.assert_driver_may_view_shipment(owner, shipment)
        )

    def test_driver_views_own_shipment(self):
        owner = _driver()
        shipment = _shipment(driver_id=owner.pk)
        self.assertTrue(
            HardPodProjectionService.assert_driver_may_view_shipment(owner, shipment)
        )


class HardPodListServiceOwnershipTests(SimpleTestCase):
    @patch('mobile_api.hard_pod.services.hard_pod_list_service.schema_context')
    @patch.object(HardPodProjectionService, 'build_rows_for_shipments')
    @patch.object(HardPodListService, '_query_driver_hard_pod_shipments')
    def test_list_pending_returns_rows(
        self,
        mock_query,
        mock_build,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        shipment = _shipment()
        mock_query.return_value = [shipment]
        mock_build.return_value = [
            {
                'shipment_id': str(shipment.pk),
                'job_no': shipment.shipment_no,
                'hard_pod_pending': True,
                'custody_state': CUSTODY_NOT_STARTED,
                'verification_state': 'pending',
                'receiver': {},
                'handoff': {},
                'timeline_preview': [],
                'workflow_blocked': False,
                'reconciliation': {
                    'custody_vs_workflow_mismatch': False,
                    'missing_hard_pod_log': False,
                },
            }
        ]
        driver = _driver()
        result = HardPodListService().list_pending(
            driver=driver,
            tenant_schema='tenant_a',
        )
        self.assertEqual(result['count'], 1)
        self.assertEqual(len(result['items']), 1)

    @patch('mobile_api.hard_pod.services.hard_pod_list_service.schema_context')
    def test_list_requires_tenant_schema(self, mock_schema):
        driver = _driver()
        result = HardPodListService().list_pending(
            driver=driver,
            tenant_schema='',
        )
        self.assertTrue(result.get('error'))
        self.assertEqual(result.get('code'), 'tenant_required')
        mock_schema.assert_not_called()


class HardPodListIntegrationTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant_schema = 'tenant_hard_pod_test'
        self.driver_id = str(uuid.uuid4())
        self.shipment_id = str(uuid.uuid4())

    def _create_bundle(self) -> PODCaptureBundle:
        now = timezone.now()
        return PODCaptureBundle.objects.create(
            id=uuid.uuid4(),
            tenant_schema=self.tenant_schema,
            shipment_id=self.shipment_id,
            driver_id=self.driver_id,
            client_capture_id=f'cap-{uuid.uuid4()}',
            bundle_status=PODCaptureBundle.BundleStatus.READY,
            expires_at=now + timedelta(hours=48),
            pod_type='hard',
        )

    @patch('mobile_api.hard_pod.services.hard_pod_projection_service.pod_cod_policy')
    def test_custody_projection_from_db(self, mock_policy) -> None:
        mock_policy.derive_pod_cod_flags.return_value = {
            'hard_pod_pending': True,
            'delivery_blocked': False,
        }
        mock_policy.derive_delivery_blocked.return_value = False

        bundle = self._create_bundle()
        submission = HardPODCustodySubmission.objects.create(
            tenant_schema=self.tenant_schema,
            shipment_id=self.shipment_id,
            driver_id=self.driver_id,
            client_submission_id=f'custody-{uuid.uuid4()}',
            receiver_name='Receiver One',
        )
        HardPODCustodySubmissionEvent.objects.create(
            submission=submission,
            tenant_schema=self.tenant_schema,
            shipment_id=self.shipment_id,
            driver_id=self.driver_id,
            event_type=HardPODCustodySubmissionEvent.EventType.COLLECTED,
            actor_label='Driver',
        )

        custody = HardPodProjectionService().build_row(
            _shipment(pk=self.shipment_id, driver_id=self.driver_id),
            driver=_driver(self.driver_id),
            tenant_schema=self.tenant_schema,
            custody_bundle={
                'events': list(submission.custody_events.all()),
                'receipt': None,
                'verification': None,
                'submission': submission,
                'bundle_id': str(bundle.id),
            },
        )
        self.assertEqual(custody['custody_state'], CUSTODY_COLLECTED)
        self.assertEqual(custody['receiver']['name'], 'Receiver One')

    @patch('mobile_api.hard_pod.services.hard_pod_projection_service.pod_cod_policy')
    def test_verified_custody_state(self, mock_policy) -> None:
        mock_policy.derive_pod_cod_flags.return_value = {
            'hard_pod_pending': False,
            'delivery_blocked': False,
        }
        mock_policy.derive_delivery_blocked.return_value = False

        bundle = self._create_bundle()
        submission = HardPODCustodySubmission.objects.create(
            tenant_schema=self.tenant_schema,
            shipment_id=self.shipment_id,
            driver_id=self.driver_id,
            client_submission_id=f'verified-{uuid.uuid4()}',
            capture_bundle_id=bundle.id,
        )
        HardPODCustodySubmissionEvent.objects.create(
            submission=submission,
            tenant_schema=self.tenant_schema,
            shipment_id=self.shipment_id,
            driver_id=self.driver_id,
            event_type=HardPODCustodySubmissionEvent.EventType.VERIFIED,
            actor_label='Supervisor',
        )
        custody = HardPodProjectionService().build_row(
            _shipment(pk=self.shipment_id, driver_id=self.driver_id),
            driver=_driver(self.driver_id),
            tenant_schema=self.tenant_schema,
            custody_bundle={
                'events': list(submission.custody_events.all()),
                'receipt': None,
                'verification': None,
                'submission': submission,
                'bundle_id': str(bundle.id),
            },
        )
        self.assertEqual(custody['verification_state'], VERIFICATION_VERIFIED)
        self.assertEqual(custody['custody_state'], CUSTODY_VERIFIED)

    @patch('mobile_api.hard_pod.services.hard_pod_projection_service.pod_cod_policy')
    @patch(
        'mobile_api.hard_pod.services.hard_pod_projection_service._load_portal_pod_documents'
    )
    @patch(
        'mobile_api.hard_pod.services.hard_pod_projection_service._load_custody_by_shipment'
    )
    @patch(
        'mobile_api.hard_pod.services.hard_pod_projection_service._load_action_logs_by_shipment'
    )
    def test_empty_queue_when_not_pending(
        self,
        mock_logs,
        mock_custody,
        mock_portal,
        mock_policy,
    ) -> None:
        mock_logs.return_value = {}
        mock_custody.return_value = {}
        mock_portal.return_value = {}
        mock_policy.derive_pod_cod_flags.return_value = {
            'hard_pod_pending': False,
            'delivery_blocked': False,
        }
        mock_policy.derive_delivery_blocked.return_value = False

        rows = HardPodProjectionService().build_rows_for_shipments(
            [
                _shipment(
                    pk=self.shipment_id,
                    driver_id=self.driver_id,
                    pod_status=TenantShipment.PodStatus.HARD_COPY_RECEIVED,
                )
            ],
            driver=_driver(self.driver_id),
            tenant_schema=self.tenant_schema,
            pending_only=True,
        )
        self.assertEqual(rows, [])
