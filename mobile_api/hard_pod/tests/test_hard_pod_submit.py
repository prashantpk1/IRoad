"""
Hard POD custody submit — replay, security, append-only tests.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from mobile_api.hard_pod.exceptions import HardPodError
from mobile_api.hard_pod.guards.hard_pod_replay_guard import HardPodReplayGuard
from mobile_api.hard_pod.guards.hard_pod_security_guard import (
    HardPodSecurityGuard,
    build_hard_pod_upload_prefix,
)
from mobile_api.hard_pod.models import (
    HardPODCustodySubmission,
    HardPODCustodySubmissionEvent,
    HardPODCustodySubmissionMedia,
)
from mobile_api.hard_pod.services.hard_pod_custody_service import HardPodCustodyService
from mobile_api.hard_pod.services.hard_pod_idempotency_service import HardPodIdempotencyService
from mobile_api.hard_pod.services.hard_pod_submit_service import HardPodSubmitService
from tenant_workspace.models import TenantShipment


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid.uuid4()
    d.driver_id = d.pk
    d.driver_status = 'Active'
    d.driver_no = 'DRV-1'
    return d


def _hard_shipment(pk=None, driver_id=None):
    s = MagicMock()
    s.pk = pk or uuid.uuid4()
    s.shipment_id = s.pk
    s.shipment_no = 'SH-HARD-99'
    s.pod_type = TenantShipment.PodType.HARD
    s.shipment_status = TenantShipment.ShipmentStatus.LOADED
    s.driver_id = driver_id
    s.booking = None
    return s


class HardPodSecurityGuardTests(SimpleTestCase):
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.schema_context')
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.lookup_shipment_by_reference')
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.shipment_is_driver_accessible')
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.driver_owns_shipment_leg')
    def test_wrong_driver_forbidden(
        self,
        mock_owns,
        mock_accessible,
        mock_lookup,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        shipment = _hard_shipment()
        mock_lookup.return_value = shipment
        mock_accessible.return_value = True
        mock_owns.return_value = False

        guard = HardPodSecurityGuard()
        with self.assertRaises(HardPodError) as exc:
            guard.resolve_and_assert_shipment(
                driver=_driver(),
                tenant_schema='tenant_a',
                shipment_id=str(shipment.pk),
            )
        self.assertEqual(exc.exception.code, 'forbidden')

    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.schema_context')
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.lookup_shipment_by_reference')
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.shipment_is_driver_accessible')
    @patch('mobile_api.hard_pod.guards.hard_pod_security_guard.driver_owns_shipment_leg')
    def test_not_hard_pod_shipment_rejected(
        self,
        mock_owns,
        mock_accessible,
        mock_lookup,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        shipment = _hard_shipment()
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        mock_lookup.return_value = shipment
        mock_accessible.return_value = True
        mock_owns.return_value = True

        with self.assertRaises(HardPodError) as exc:
            HardPodSecurityGuard().resolve_and_assert_shipment(
                driver=_driver(shipment.driver_id),
                tenant_schema='tenant_a',
                shipment_id=str(shipment.pk),
            )
        self.assertEqual(exc.exception.code, 'not_hard_pod_shipment')

    def test_orphan_media_path_rejected(self):
        driver_id = str(uuid.uuid4())
        shipment_id = str(uuid.uuid4())
        prefix = build_hard_pod_upload_prefix(
            tenant_schema='tenant_a',
            driver_pk=driver_id,
            shipment_pk=shipment_id,
        )
        self.assertIn('hard_pod', prefix)
        with self.assertRaises(HardPodError) as exc:
            HardPodSecurityGuard().assert_media_paths(
                [{'file_ref': 'tenant-uploads/orphan.jpg'}],
                tenant_schema='tenant_a',
                driver_pk=driver_id,
                shipment_pk=shipment_id,
            )
        self.assertEqual(exc.exception.code, 'orphan_upload')


class HardPodReplayGuardTests(SimpleTestCase):
    def test_submission_shipment_mismatch_on_replay(self):
        existing = HardPODCustodySubmission(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='ship-a',
            client_submission_id='sub-1',
        )
        guard = HardPodReplayGuard()
        with self.assertRaises(HardPodError) as exc:
            guard.assert_replay_scope(
                existing,
                shipment_id='ship-b',
                driver_id='drv-1',
                tenant_schema='tenant_a',
            )
        self.assertEqual(exc.exception.code, 'submission_shipment_mismatch')


class HardPodSubmitServiceTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant_schema = 'tenant_hard_submit'
        self.driver_id = str(uuid.uuid4())
        self.shipment_id = str(uuid.uuid4())
        self.client_submission_id = f'client-sub-{uuid.uuid4()}'
        self.driver = _driver(self.driver_id)
        self.shipment = _hard_shipment(self.shipment_id, self.driver_id)

    def _payload(self, **kwargs) -> dict:
        base = {
            'client_submission_id': self.client_submission_id,
            'shipment_id': self.shipment_id,
            'receiver_name': 'Jane Receiver',
            'receiver_contact': '+966500000000',
            'handoff_notes': 'Left with security desk',
            'latitude': 24.7136,
            'longitude': 46.6753,
            'media': [],
        }
        base.update(kwargs)
        return base

    @patch('mobile_api.hard_pod.services.hard_pod_submit_service.schema_context')
    @patch.object(HardPodSecurityGuard, 'resolve_and_assert_shipment')
    @patch.object(HardPodSecurityGuard, 'assert_media_paths')
    def test_successful_submit_creates_custody(
        self,
        mock_media,
        mock_resolve,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_resolve.return_value = self.shipment

        service = HardPodSubmitService()
        result = service.submit_custody(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            payload=self._payload(),
        )

        self.assertFalse(result['custody_submission']['replayed'])
        self.assertTrue(result['next_step']['requires_execute_action'])
        self.assertEqual(result['custody_submission']['receiver_name'], 'Jane Receiver')
        self.assertGreaterEqual(len(result['timeline_preview']), 1)

        submission = HardPODCustodySubmission.objects.get(
            client_submission_id=self.client_submission_id,
        )
        self.assertEqual(submission.receiver_contact, '+966500000000')
        # collected, handoff, received, verified
        self.assertEqual(submission.custody_events.count(), 4)

    @patch('mobile_api.hard_pod.services.hard_pod_submit_service.schema_context')
    @patch.object(HardPodSecurityGuard, 'resolve_and_assert_shipment')
    def test_wrong_shipment_rejected(self, mock_resolve, mock_schema):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_resolve.side_effect = HardPodError(
            'not found',
            code='job_not_found',
            http_status=404,
            message_key='mobile.jobs.not_found',
        )

        with self.assertRaises(HardPodError) as exc:
            HardPodSubmitService().submit_custody(
                driver=self.driver,
                tenant_schema=self.tenant_schema,
                payload=self._payload(),
            )
        self.assertEqual(exc.exception.code, 'job_not_found')

    @patch('mobile_api.hard_pod.services.hard_pod_submit_service.schema_context')
    @patch.object(HardPodSecurityGuard, 'resolve_and_assert_shipment')
    def test_wrong_driver_rejected(self, mock_resolve, mock_schema):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_resolve.side_effect = HardPodError(
            'forbidden',
            code='forbidden',
            http_status=403,
            message_key='mobile.auth.forbidden',
        )

        with self.assertRaises(HardPodError) as exc:
            HardPodSubmitService().submit_custody(
                driver=self.driver,
                tenant_schema=self.tenant_schema,
                payload=self._payload(),
            )
        self.assertEqual(exc.exception.code, 'forbidden')

    @patch('mobile_api.hard_pod.services.hard_pod_submit_service.schema_context')
    @patch.object(HardPodSecurityGuard, 'resolve_and_assert_shipment')
    @patch.object(HardPodSecurityGuard, 'assert_media_paths')
    def test_replay_submit_returns_same_submission(
        self,
        mock_media,
        mock_resolve,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_resolve.return_value = self.shipment

        service = HardPodSubmitService()
        first = service.submit_custody(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            payload=self._payload(),
        )
        second = service.submit_custody(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            payload=self._payload(),
        )

        self.assertFalse(first['custody_submission']['replayed'])
        self.assertTrue(second['custody_submission']['replayed'])
        self.assertEqual(
            first['custody_submission']['submission_id'],
            second['custody_submission']['submission_id'],
        )
        self.assertEqual(
            HardPODCustodySubmission.objects.filter(
                client_submission_id=self.client_submission_id,
            ).count(),
            1,
        )

    @patch('mobile_api.hard_pod.services.hard_pod_submit_service.schema_context')
    @patch.object(HardPodSecurityGuard, 'resolve_and_assert_shipment')
    @patch.object(HardPodSecurityGuard, 'assert_media_paths')
    def test_duplicate_race_returns_replay(
        self,
        mock_media,
        mock_resolve,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_resolve.return_value = self.shipment

        HardPODCustodySubmission.objects.create(
            tenant_schema=self.tenant_schema,
            driver_id=self.driver_id,
            shipment_id=self.shipment_id,
            client_submission_id=self.client_submission_id,
            receiver_name='Pre-existing',
        )

        # Client retries the same submission key. The service must return replay.
        result = HardPodSubmitService().submit_custody(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            payload=self._payload(),
        )

        self.assertTrue(result['custody_submission']['replayed'])

    @patch('mobile_api.hard_pod.services.hard_pod_submit_service.schema_context')
    @patch.object(HardPodSecurityGuard, 'resolve_and_assert_shipment')
    @patch.object(HardPodSecurityGuard, 'assert_media_paths')
    def test_immutable_media_persisted(
        self,
        mock_media,
        mock_resolve,
        mock_schema,
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)
        mock_resolve.return_value = self.shipment

        prefix = build_hard_pod_upload_prefix(
            tenant_schema=self.tenant_schema,
            driver_pk=self.driver_id,
            shipment_pk=self.shipment_id,
        )
        payload = self._payload(
            client_submission_id=f'media-{uuid.uuid4()}',
            media=[
                {
                    'media_type': 'photo',
                    'file_ref': f'{prefix}scan.jpg',
                    'file_name': 'scan.jpg',
                }
            ],
        )
        result = HardPodSubmitService().submit_custody(
            driver=self.driver,
            tenant_schema=self.tenant_schema,
            payload=payload,
        )
        submission_id = result['custody_submission']['submission_id']
        media = HardPODCustodySubmissionMedia.objects.filter(
            submission_id=submission_id,
        ).first()
        self.assertIsNotNone(media)
        self.assertTrue(media.immutable)

        # Media evidence is immutable: updates are rejected.
        with self.assertRaises(ValueError):
            media.file_name = 'changed.jpg'
            media.save()

    def test_custody_event_append_only(self) -> None:
        submission = HardPODCustodySubmission.objects.create(
            tenant_schema=self.tenant_schema,
            driver_id=self.driver_id,
            shipment_id=self.shipment_id,
            client_submission_id=f'append-{uuid.uuid4()}',
        )
        event = HardPodCustodyService().append_event(
            submission,
            event_type=HardPODCustodySubmissionEvent.EventType.COLLECTED,
            actor_id=self.driver_id,
        )
        event.notes = 'mutated'
        with self.assertRaises(ValueError):
            event.save()

    def test_idempotency_unique_constraint(self) -> None:
        cid = f'uniq-{uuid.uuid4()}'
        HardPodIdempotencyService().create_submission(
            tenant_schema=self.tenant_schema,
            driver_id=self.driver_id,
            shipment_id=self.shipment_id,
            client_submission_id=cid,
            receiver_name='A',
        )
        with self.assertRaises(IntegrityError):
            HardPODCustodySubmission.objects.create(
                tenant_schema=self.tenant_schema,
                driver_id=self.driver_id,
                shipment_id=self.shipment_id,
                client_submission_id=cid,
            )
