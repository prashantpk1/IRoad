"""
DB-backed enterprise integration tests for durable POD capture.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase
from django.utils import timezone

from mobile_api.pod_capture.dto.promotion_models import PodPromotionRequest, PodPromotionScope
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.guards.immutable_evidence_guard import ImmutableEvidenceGuard
from mobile_api.pod_capture.models import PODCapturePromotionAudit
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    classify_timeline_event_type,
    is_pod_upload_action,
    is_unloading_action,
)
from mobile_api.pod_capture.repositories.durable_bundle_repository import DurableBundleRepository
from mobile_api.pod_capture.services.action_log_bundle_link import (
    bundle_source_ref,
    parse_bundle_id_from_source_ref,
)
from mobile_api.pod_capture.services.hard_pod_custody_service import HardPODCustodyService
from mobile_api.pod_capture.services.media_integrity_service import MediaIntegrityService
from mobile_api.pod_capture.services.promotion_audit_service import PromotionAuditService
from mobile_api.pod_capture.staging.evidence_promotion_service import EvidencePromotionService
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


def _scope(**kwargs) -> StagingScope:
    defaults = dict(
        tenant_schema='tenant_int',
        driver_id='drv-int',
        shipment_id='ship-int',
        client_capture_id='cap-int',
    )
    defaults.update(kwargs)
    return StagingScope(**defaults)


class PodCaptureEnterpriseIntegrationTests(TransactionTestCase):
    def setUp(self) -> None:
        self.repo = DurableBundleRepository()
        self.staging = EvidenceStagingService(repository=self.repo)
        self.integrity = MediaIntegrityService()
        self.scope = _scope()

    def _ready_bundle_with_media(self) -> PODCaptureBundle:
        now = timezone.now()
        bundle = PODCaptureBundle(
            bundle_id=str(uuid.uuid4()),
            client_capture_id=self.scope.client_capture_id,
            shipment_id=self.scope.shipment_id,
            driver_id=self.scope.driver_id,
            tenant_schema=self.scope.tenant_schema,
            status=PODCaptureBundleStatus.READY,
            content_hash='hash-int',
            media_count=1,
            expires_at=now + timedelta(hours=48),
            created_at=now,
            updated_at=now,
        )
        media = PODCaptureMedia(
            media_id=str(uuid.uuid4()),
            bundle_id=bundle.bundle_id,
            shipment_id=self.scope.shipment_id,
            driver_id=self.scope.driver_id,
            tenant_schema=self.scope.tenant_schema,
            client_capture_id=self.scope.client_capture_id,
            media_type='photo',
            file_ref=f'{self.scope.storage_prefix()}photo.jpg',
            checksum='',
            line_no=1,
        )
        self.integrity.assign_media_checksums([media])
        bundle.integrity_checksum = self.integrity.seal_bundle(bundle, [media])
        self.repo.save_bundle(bundle)
        self.repo.save_media(bundle.bundle_id, [media])
        return bundle

    def test_durable_bundle_persists_and_reloads(self) -> None:
        bundle = self._ready_bundle_with_media()
        loaded = self.repo.get_bundle(bundle.bundle_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.bundle_id, bundle.bundle_id)
        self.assertEqual(len(self.repo.get_media(bundle.bundle_id)), 1)

    def test_restart_safe_idempotent_replay(self) -> None:
        driver = SimpleNamespace(pk=self.scope.driver_id, driver_id=self.scope.driver_id)
        ctx = SimpleNamespace(
            driver=driver,
            tenant_schema=self.scope.tenant_schema,
            shipment_id=self.scope.shipment_id,
            payload={},
            client_capture_id='cap-restart',
            content_hash='h',
            idempotent_replay=False,
            bundle=None,
            staged_media=[],
        )
        from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext

        real_ctx = PodCaptureContext(
            driver=driver,
            tenant_schema=self.scope.tenant_schema,
            shipment_id=self.scope.shipment_id,
            payload={},
            client_capture_id='cap-restart',
            content_hash='h',
        )
        first = self.staging.stage_bundle(real_ctx)
        staging2 = EvidenceStagingService(repository=DurableBundleRepository())
        ctx2 = PodCaptureContext(
            driver=driver,
            tenant_schema=self.scope.tenant_schema,
            shipment_id=self.scope.shipment_id,
            payload={},
            client_capture_id='cap-restart',
            content_hash='h',
        )
        second = staging2.stage_bundle(ctx2)
        self.assertEqual(first.bundle_id, second.bundle_id)

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.link_action_log_to_bundle'
    )
    def test_promotion_audit_and_action_log_link(self, mock_link, mock_persist) -> None:
        mock_persist.return_value = [uuid.uuid4()]
        bundle = self._ready_bundle_with_media()
        action_log = MagicMock(pk=uuid.uuid4(), source_ref='')
        action_log.save = MagicMock()

        promo = EvidencePromotionService(staging=self.staging)
        scope = PodPromotionScope(
            tenant_schema=self.scope.tenant_schema,
            driver_id=self.scope.driver_id,
            shipment_id=self.scope.shipment_id,
        )
        result = promo.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=bundle.bundle_id,
                action_log=action_log,
                scope=scope,
            ),
            promoted_by='drv-int',
            execution_idempotency_key='exec-1',
        )
        self.assertFalse(result.replayed)
        mock_link.assert_called_once()
        self.assertTrue(
            PODCapturePromotionAudit.objects.filter(
                bundle_id=bundle.bundle_id,
                action_log_id=str(action_log.pk),
            ).exists()
        )

    def test_timeline_a7_pod_a8_movement(self) -> None:
        a7 = SimpleNamespace(
            action_code='A7',
            english_label='Upload POD',
            auto_pod_post=True,
            hard_copy_collection=False,
            shipment_status_impact='',
            movement_status_impact='',
        )
        a8 = SimpleNamespace(
            action_code='A8',
            english_label='Unloading',
            auto_pod_post=False,
            hard_copy_collection=False,
            shipment_status_impact='',
            movement_status_impact='In Transit',
        )
        self.assertTrue(is_pod_upload_action(a7))
        self.assertFalse(is_unloading_action(a7))
        self.assertEqual(classify_timeline_event_type(a7), 'pod')
        self.assertEqual(classify_timeline_event_type(a8), 'movement')

    def test_hard_pod_custody_chain(self) -> None:
        bundle = self._ready_bundle_with_media()
        custody = HardPODCustodyService()
        receipt = custody.record_collection(
            bundle,
            document_serial='DN-100',
            receiver_name='Receiver',
        )
        custody.record_received(receipt, actor_label='Hub')
        custody.record_supervisor_verification(
            bundle,
            supervisor_id='sup-1',
            supervisor_label='Supervisor',
        )
        entries = custody.timeline_entries_for_bundle(bundle.bundle_id)
        self.assertGreaterEqual(len(entries), 3)

    def test_stale_bundle_expired_by_ttl_command(self) -> None:
        bundle = self._ready_bundle_with_media()
        bundle.expires_at = timezone.now() - timedelta(minutes=5)
        bundle.status = PODCaptureBundleStatus.READY
        self.repo.update_bundle(bundle)
        count = self.repo.expire_stale_bundles()
        self.assertGreaterEqual(count, 1)
        reloaded = self.repo.get_bundle(bundle.bundle_id)
        self.assertEqual(reloaded.status, PODCaptureBundleStatus.EXPIRED)

    def test_immutable_guard_blocks_replace(self) -> None:
        guard = ImmutableEvidenceGuard()
        with self.assertRaises(PodCaptureError):
            guard.assert_replace_allowed(
                replace_existing=True,
                immutable=True,
            )

    def test_bundle_source_ref_roundtrip(self) -> None:
        bid = str(uuid.uuid4())
        ref = bundle_source_ref(bid)
        self.assertEqual(parse_bundle_id_from_source_ref(ref), bid)

    def test_integrity_checksum_mismatch_rejected(self) -> None:
        bundle = self._ready_bundle_with_media()
        media = self.repo.get_media(bundle.bundle_id)
        bundle.integrity_checksum = 'deadbeef'
        self.repo.update_bundle(bundle)
        with self.assertRaises(PodCaptureError) as exc:
            self.integrity.verify_bundle_integrity(bundle, media)
        self.assertEqual(exc.exception.code, 'integrity_checksum_mismatch')
