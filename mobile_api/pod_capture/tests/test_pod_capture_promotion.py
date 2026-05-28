"""
POD bundle promotion, immutability, and Execute-phase safety tests.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.tests.transaction_test_case import TransactionTestCase
from django.utils import timezone

from mobile_api.pod_capture.dto.promotion_models import PodPromotionRequest, PodPromotionScope
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.policy.pod_evidence_immutability_policy import (
    POD_EVIDENCE_REPLACE_EXISTING,
    persist_pod_action_log_media,
)
from mobile_api.pod_capture.services.pod_capture_bundle_service import PodCaptureBundleService
from mobile_api.pod_capture.staging.evidence_promotion_service import (
    EvidencePromotionService,
    staged_media_to_action_log_items,
)
from mobile_api.pod_capture.repositories.durable_bundle_repository import (
    DurableBundleRepository,
)
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


def _scope(**kwargs) -> StagingScope:
    defaults = dict(
        tenant_schema='tenant_a',
        driver_id='drv-1',
        shipment_id='ship-1',
        client_capture_id='cap-1',
    )
    defaults.update(kwargs)
    return StagingScope(**defaults)


def _ready_bundle(scope: StagingScope, *, bundle_id: str | None = None) -> PODCaptureBundle:
    now = timezone.now()
    return PODCaptureBundle(
        bundle_id=bundle_id or str(uuid.uuid4()),
        client_capture_id=scope.client_capture_id,
        shipment_id=scope.shipment_id,
        driver_id=scope.driver_id,
        tenant_schema=scope.tenant_schema,
        status=PODCaptureBundleStatus.READY,
        content_hash='hash-1',
        media_count=1,
        expires_at=now + timedelta(hours=24),
        created_at=now,
        updated_at=now,
    )


def _media(scope: StagingScope, bundle_id: str) -> PODCaptureMedia:
    return PODCaptureMedia(
        media_id=str(uuid.uuid4()),
        bundle_id=bundle_id,
        shipment_id=scope.shipment_id,
        driver_id=scope.driver_id,
        tenant_schema=scope.tenant_schema,
        client_capture_id=scope.client_capture_id,
        media_type='photo',
        file_ref=f'{scope.storage_prefix()}photo.jpg',
        line_no=1,
    )


class PodEvidenceImmutabilityPolicyTests(SimpleTestCase):
    def test_pod_never_uses_replace_existing(self) -> None:
        self.assertFalse(POD_EVIDENCE_REPLACE_EXISTING)

    @patch(
        'mobile_api.pod_capture.policy.pod_evidence_immutability_policy.persist_action_log_media_rows'
    )
    def test_persist_pod_media_append_only(self, mock_persist) -> None:
        mock_persist.return_value = ['row-1']
        action_log = object()
        items = []
        result = persist_pod_action_log_media(action_log, items)
        mock_persist.assert_called_once_with(
            action_log,
            items,
            replace_existing=False,
            immutable=True,
        )
        self.assertEqual(result, ['row-1'])


class EvidencePromotionFlowTests(TransactionTestCase):
    def setUp(self) -> None:
        self.repo = DurableBundleRepository()
        self.staging = EvidenceStagingService(repository=self.repo)
        self.bundles = PodCaptureBundleService(staging=self.staging)
        self.promotion = EvidencePromotionService(
            staging=self.staging,
            bundle_service=self.bundles,
        )
        self.scope = _scope()
        self.promo_scope = PodPromotionScope(
            tenant_schema=self.scope.tenant_schema,
            driver_id=self.scope.driver_id,
            shipment_id=self.scope.shipment_id,
        )
        self.bundle = _ready_bundle(self.scope)
        self.repo.save_bundle(self.bundle)
        self.repo.save_media(
            self.bundle.bundle_id,
            [_media(self.scope, self.bundle.bundle_id)],
        )

    def _action_log(self, pk: str | None = None) -> MagicMock:
        log = MagicMock()
        log.pk = pk or uuid.uuid4()
        log.media_rows = MagicMock()
        log.media_rows.filter.return_value.first.return_value = None
        return log

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    def test_successful_promotion(self, mock_persist) -> None:
        mock_persist.return_value = [uuid.uuid4()]
        action_log = self._action_log()

        result = self.promotion.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=self.bundle.bundle_id,
                action_log=action_log,
                scope=self.promo_scope,
            )
        )

        self.assertFalse(result.replayed)
        self.assertEqual(result.action_log_id, str(action_log.pk))
        self.assertEqual(len(result.media_row_ids), 1)
        mock_persist.assert_called_once()
        items = mock_persist.call_args[0][1]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].file_ref, f'{self.scope.storage_prefix()}photo.jpg')

        promoted = self.staging.get_bundle(self.bundle.bundle_id)
        self.assertEqual(promoted.status, PODCaptureBundleStatus.PROMOTED)
        self.assertEqual(promoted.promotion_action_log_id, str(action_log.pk))
        self.assertIsNotNone(promoted.promoted_at)

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    def test_replay_promotion_same_action_log(self, mock_persist) -> None:
        action_log = self._action_log()
        first = self.promotion.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=self.bundle.bundle_id,
                action_log=action_log,
                scope=self.promo_scope,
            )
        )
        self.assertFalse(first.replayed)
        self.assertEqual(mock_persist.call_count, 1)

        second = self.promotion.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=self.bundle.bundle_id,
                action_log=action_log,
                scope=self.promo_scope,
            )
        )
        self.assertTrue(second.replayed)
        self.assertEqual(mock_persist.call_count, 1)

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    def test_double_promotion_different_action_log(self, mock_persist) -> None:
        mock_persist.return_value = [uuid.uuid4()]
        first_log = self._action_log()
        self.promotion.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=self.bundle.bundle_id,
                action_log=first_log,
                scope=self.promo_scope,
            )
        )

        second_log = self._action_log()
        with self.assertRaises(PodCaptureError) as exc:
            self.promotion.promote_staged_bundle(
                PodPromotionRequest(
                    bundle_id=self.bundle.bundle_id,
                    action_log=second_log,
                    scope=self.promo_scope,
                )
            )
        self.assertEqual(exc.exception.code, 'bundle_already_promoted')

    def test_cross_shipment_promotion_rejected(self) -> None:
        wrong_scope = PodPromotionScope(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='ship-other',
        )
        with self.assertRaises(PodCaptureError) as exc:
            self.promotion.promote_staged_bundle(
                PodPromotionRequest(
                    bundle_id=self.bundle.bundle_id,
                    action_log=self._action_log(),
                    scope=wrong_scope,
                )
            )
        self.assertEqual(exc.exception.code, 'capture_id_shipment_mismatch')

    def test_cross_driver_promotion_rejected(self) -> None:
        wrong_scope = PodPromotionScope(
            tenant_schema='tenant_a',
            driver_id='drv-other',
            shipment_id='ship-1',
        )
        with self.assertRaises(PodCaptureError) as exc:
            self.promotion.promote_staged_bundle(
                PodPromotionRequest(
                    bundle_id=self.bundle.bundle_id,
                    action_log=self._action_log(),
                    scope=wrong_scope,
                )
            )
        self.assertEqual(exc.exception.code, 'driver_scope_mismatch')

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    def test_immutable_evidence_after_promotion(self, mock_persist) -> None:
        mock_persist.return_value = [uuid.uuid4()]
        self.promotion.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=self.bundle.bundle_id,
                action_log=self._action_log(),
                scope=self.promo_scope,
            )
        )

        from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext

        promoted = self.staging.get_bundle(self.bundle.bundle_id)
        ctx = PodCaptureContext(
            driver=SimpleNamespace(pk=promoted.driver_id, driver_id=promoted.driver_id),
            tenant_schema=promoted.tenant_schema,
            shipment_id=promoted.shipment_id,
            payload={},
        )
        ctx.bundle = promoted
        ctx.client_capture_id = promoted.client_capture_id
        ctx.idempotent_replay = False
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_bundle_mutable_for_capture(promoted)
        self.assertEqual(exc.exception.code, 'bundle_already_promoted')

        with self.assertRaises(PodCaptureError) as exc2:
            self.staging.attach_media(ctx, [_media(self.scope, promoted.bundle_id)])
        self.assertIn(
            exc2.exception.code,
            {'bundle_already_promoted', 'bundle_immutable', 'upload_already_promoted'},
        )

    def test_orphan_bundle_prevention(self) -> None:
        with self.assertRaises(PodCaptureError) as exc:
            self.promotion.promote_staged_bundle(
                PodPromotionRequest(
                    bundle_id='00000000-0000-0000-0000-000000000099',
                    action_log=self._action_log(),
                    scope=self.promo_scope,
                )
            )
        self.assertEqual(exc.exception.code, 'bundle_not_found')

    def test_staged_media_maps_without_replace_semantics(self) -> None:
        row = _media(self.scope, self.bundle.bundle_id)
        items = staged_media_to_action_log_items([row])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].media_id, '')

    def test_bundle_service_execute_reference(self) -> None:
        ref = self.bundles.build_execute_bundle_reference(self.bundle)
        self.assertTrue(ref['ready_for_execute'])
        self.assertEqual(ref['bundle_id'], self.bundle.bundle_id)
