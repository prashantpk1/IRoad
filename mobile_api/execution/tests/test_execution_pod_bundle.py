"""
Execute Action integration with staged POD capture bundles.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execute_action_result import ExecuteActionResult
from mobile_api.execution.evidence.action_log_media_persistence import (
    ActionLogMediaItem,
    persist_action_log_media_rows,
)
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
    extract_capture_bundle_id,
)
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.services.execute_action_orchestrator import (
    ExecuteActionOrchestrator,
)
from mobile_api.pod_capture.dto.promotion_models import PodPromotionScope
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.staging.evidence_staging_service import (
    EvidenceStagingService,
    _InMemoryStagingStore,
)
from mobile_api.pod_capture.models import PODCaptureBundle as PODCaptureBundleORM


@contextmanager
def _fake_schema(_name):
    yield


def _driver():
    return SimpleNamespace(pk='drv-1', driver_id='drv-1', driver_name='Driver')


def _shipment():
    return SimpleNamespace(
        pk='ship-1',
        shipment_id='ship-1',
        shipment_no='SHP-1',
        booking_item_type='outbound',
        booking=SimpleNamespace(pk='bk-1'),
        truck=None,
    )


def _action_log():
    log = MagicMock()
    log.pk = uuid4()
    log.log_id = log.pk
    log.log_no = 'OAL-POD-1'
    log.log_date = None
    log.media_rows = MagicMock()
    log.media_rows.filter.return_value.first.return_value = None
    log.media_rows.exclude.return_value.delete = MagicMock()
    return log


def _ready_bundle(scope: StagingScope) -> PODCaptureBundle:
    now = timezone.now()
    return PODCaptureBundle(
        bundle_id=str(uuid4()),
        client_capture_id='cap-exec-1',
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


class ActionLogMediaImmutabilityTests(SimpleTestCase):
    @patch('mobile_api.execution.evidence.action_log_media_persistence.TenantOperationActionMedia')
    def test_immutable_persist_never_replaces_or_updates(self, mock_media_cls) -> None:
        action_log = _action_log()
        existing = MagicMock()
        existing.pk = uuid4()
        action_log.media_rows.filter.return_value.first.return_value = existing

        created_row = MagicMock()
        created_row.pk = uuid4()
        mock_media_cls.return_value = created_row

        items = [
            ActionLogMediaItem(
                media_type='photo',
                file_ref='mobile_driver_uploads/t/d/s/pod_capture/a.jpg',
                media_id=str(existing.pk),
            )
        ]

        created = persist_action_log_media_rows(
            action_log,
            items,
            replace_existing=True,
            immutable=True,
        )

        self.assertEqual(len(created), 1)
        action_log.media_rows.exclude.return_value.delete.assert_not_called()
        existing.save.assert_not_called()
        action_log.media_rows.filter.assert_not_called()


class EvidencePodBundleValidationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.store = _InMemoryStagingStore()
        self.staging = EvidenceStagingService(store=self.store)
        self.scope = StagingScope(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='ship-1',
            client_capture_id='cap-1',
        )
        self.bundle = _ready_bundle(self.scope)
        self.store.save_bundle(self.bundle)
        self.store.save_media(
            self.bundle.bundle_id,
            [
                PODCaptureMedia(
                    media_id='m1',
                    bundle_id=self.bundle.bundle_id,
                    shipment_id=self.scope.shipment_id,
                    driver_id=self.scope.driver_id,
                    tenant_schema=self.scope.tenant_schema,
                    client_capture_id=self.scope.client_capture_id,
                    media_type='photo',
                    file_ref=f'{self.scope.storage_prefix()}p.jpg',
                ),
            ],
        )

    def _context(self) -> ExecuteActionContext:
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id='ship-1',
            action_code='POD_CAP',
            payload={
                'capture_bundle_id': self.bundle.bundle_id,
                'latitude': '25.0',
                'longitude': '55.0',
                'notes': 'delivered',
            },
        )
        ctx.shipment = _shipment()
        ctx.operation_action = SimpleNamespace(
            action_code='POD_CAP',
            english_label='Capture POD',
            auto_pod_post=True,
            hard_copy_collection=False,
            shipment_status_impact='',
            movement_status_impact='',
            booking_status_impact='',
        )
        return ctx

    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    def test_wrong_shipment_rejected(self, mock_staging_cls) -> None:
        mock_staging_cls.return_value = self.staging
        ctx = self._context()
        ctx.job_id = 'ship-other'
        ctx.shipment = SimpleNamespace(pk='ship-other', shipment_id='ship-other')

        with self.assertRaises(ExecuteActionError) as exc:
            EvidenceValidationService().validate_pod_capture_bundle(
                ctx,
                self.bundle.bundle_id,
            )
        self.assertEqual(exc.exception.code, 'capture_id_shipment_mismatch')

    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    def test_wrong_driver_rejected(self, mock_staging_cls) -> None:
        mock_staging_cls.return_value = self.staging
        ctx = self._context()
        ctx.driver = SimpleNamespace(pk='drv-other', driver_id='drv-other')

        with self.assertRaises(ExecuteActionError) as exc:
            EvidenceValidationService().validate_pod_capture_bundle(
                ctx,
                self.bundle.bundle_id,
            )
        self.assertEqual(exc.exception.code, 'driver_scope_mismatch')

    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    def test_expired_bundle_rejected(self, mock_staging_cls) -> None:
        mock_staging_cls.return_value = self.staging
        expired = _ready_bundle(self.scope)
        expired.bundle_id = self.bundle.bundle_id
        expired.expires_at = timezone.now() - timedelta(hours=1)
        self.store.save_bundle(expired)

        ctx = self._context()
        with self.assertRaises(ExecuteActionError) as exc:
            EvidenceValidationService().validate_pod_capture_bundle(
                ctx,
                self.bundle.bundle_id,
            )
        self.assertEqual(exc.exception.code, 'bundle_expired')


class ExecutePodBundleOrchestratorTests(TransactionTestCase):
    def setUp(self) -> None:
        self.store = _InMemoryStagingStore()
        self.staging = EvidenceStagingService(store=self.store)
        self.scope = StagingScope(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='ship-1',
            client_capture_id='cap-1',
        )
        self.bundle = _ready_bundle(self.scope)
        self.store.save_bundle(self.bundle)
        media = PODCaptureMedia(
            media_id='m1',
            bundle_id=self.bundle.bundle_id,
            shipment_id=self.scope.shipment_id,
            driver_id=self.scope.driver_id,
            tenant_schema=self.scope.tenant_schema,
            client_capture_id=self.scope.client_capture_id,
            media_type='photo',
            file_ref=f'{self.scope.storage_prefix()}p.jpg',
        )
        self.store.save_media(self.bundle.bundle_id, [media])
        self.store.register_file_refs([media], replace_bundle_id=self.bundle.bundle_id)

        # Promotion audit rows have a FK to the durable ORM bundle row.
        # These orchestrator tests are wired with in-memory staging, so we
        # create the minimal ORM bundle record for referential integrity.
        PODCaptureBundleORM.objects.update_or_create(
            id=UUID(self.bundle.bundle_id),
            defaults={
                'tenant_schema': self.bundle.tenant_schema,
                'shipment_id': self.bundle.shipment_id,
                'driver_id': self.bundle.driver_id,
                'client_capture_id': self.bundle.client_capture_id,
                'workflow_version': self.bundle.workflow_version or '',
                'content_hash': self.bundle.content_hash or '',
                'bundle_status': self.bundle.status.value,
                'media_count': self.bundle.media_count,
                'expires_at': self.bundle.expires_at,
                'pod_type': self.bundle.pod_type or '',
                'notes': self.bundle.notes or '',
                'latitude': self.bundle.latitude or '',
                'longitude': self.bundle.longitude or '',
                'integrity_checksum': self.bundle.integrity_checksum or '',
                'capture_device_id': self.bundle.capture_device_id or '',
                'capture_app_version': self.bundle.capture_app_version or '',
                'promoted_at': self.bundle.promoted_at,
                'promotion_action_log_id': self.bundle.promotion_action_log_id or '',
                'replayed_from_bundle_id': None,
                'created_at': self.bundle.created_at,
            },
        )

    def _orchestrator(self) -> ExecuteActionOrchestrator:
        return ExecuteActionOrchestrator()

    def _base_payload(self) -> dict:
        return {
            'client_action_id': str(uuid4()),
            'content_hash': 'hash-pre',
            'workflow_version': 'wf-pre',
            'latitude': '25.0',
            'longitude': '55.0',
            'notes': 'execute pod',
            'capture_bundle_id': self.bundle.bundle_id,
            'media': [],
        }

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.transaction.atomic',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.EvidenceStagingService',
    )
    def test_valid_promotion_in_execute_pipeline(
        self,
        mock_promo_staging_cls,
        mock_bundle_staging_cls,
        mock_persist,
        mock_atomic,
    ) -> None:
        mock_atomic.return_value.__enter__ = MagicMock(return_value=None)
        mock_atomic.return_value.__exit__ = MagicMock(return_value=False)
        mock_persist.return_value = [uuid4()]
        mock_promo_staging_cls.return_value = self.staging
        mock_bundle_staging_cls.return_value = self.staging

        orch = self._orchestrator()
        action_log = _action_log()

        def _prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.booking = ctx.shipment.booking
            ctx.operation_action = SimpleNamespace(
                action_code='POD_CAP',
                english_label='Capture POD',
                auto_pod_post=True,
                hard_copy_collection=False,
                shipment_status_impact='',
                movement_status_impact='',
                booking_status_impact='',
            )
            ctx.workflow = {'allowed_actions': [{'action_code': 'POD_CAP'}]}
            ctx.sync_metadata = {'content_hash': 'h1'}

        def _build(ctx, **kw):
            return ExecuteActionResult(
                payload={
                    'execution': {'action_log_id': str(action_log.pk)},
                    'workflow': ctx.workflow,
                    'pod_cod': {},
                    'sync_metadata': ctx.sync_metadata,
                },
                http_status=201,
            )

        with patch.object(orch._reconcile_service, 'prepare_pre_execute', side_effect=_prepare), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch,
            '_execute_kernel',
            return_value=SimpleNamespace(action_log=action_log, reused_existing=False),
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            side_effect=_build,
        ), patch.object(
            orch._media_service,
            'persist_execution_media',
        ) as mock_media:
            result = orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant_a',
                job_type='shipment',
                job_id='ship-1',
                action_code='POD_CAP',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='u1',
            )

        mock_media.assert_not_called()
        mock_persist.assert_called_once()
        promoted = self.staging.get_bundle(self.bundle.bundle_id)
        self.assertEqual(promoted.status, PODCaptureBundleStatus.PROMOTED)
        self.assertIn('pod_capture', result.payload)
        self.assertEqual(
            result.payload['pod_capture']['promoted_bundle_id'],
            self.bundle.bundle_id,
        )
        self.assertTrue(result.payload['pod_capture']['compliance']['validated'])

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.transaction.atomic',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.EvidenceStagingService',
    )
    def test_duplicate_promotion_rejected(
        self,
        mock_promo_staging_cls,
        mock_bundle_staging_cls,
        mock_persist,
        mock_atomic,
    ) -> None:
        mock_atomic.return_value.__enter__ = MagicMock(return_value=None)
        mock_atomic.return_value.__exit__ = MagicMock(return_value=False)
        mock_persist.return_value = [uuid4()]
        mock_promo_staging_cls.return_value = self.staging
        mock_bundle_staging_cls.return_value = self.staging

        promoted = self.staging.mark_promoted(
            self.bundle,
            action_log_id=str(uuid4()),
        )
        self.assertEqual(promoted.status, PODCaptureBundleStatus.PROMOTED)

        orch = self._orchestrator()

        def _prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.operation_action = SimpleNamespace(
                action_code='POD_CAP',
                auto_pod_post=True,
                hard_copy_collection=False,
                english_label='Capture POD',
                shipment_status_impact='',
                movement_status_impact='',
                booking_status_impact='',
            )
            ctx.workflow = {}

        with patch.object(orch._reconcile_service, 'prepare_pre_execute', side_effect=_prepare), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k2', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch,
            '_execute_kernel',
            return_value=SimpleNamespace(action_log=_action_log(), reused_existing=False),
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                orch._run_execute_pipeline(
                    driver=_driver(),
                    tenant_schema='tenant_a',
                    job_type='shipment',
                    job_id='ship-1',
                    action_code='POD_CAP',
                    payload=self._base_payload(),
                    request=None,
                    tenant_user=None,
                    user_id='u1',
                )
        self.assertEqual(exc.exception.code, 'bundle_already_promoted')

    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.transaction.atomic',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.persist_pod_action_log_media'
    )
    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_promotion_service.EvidenceStagingService',
    )
    def test_replay_safe_promotion_same_action_log(
        self,
        mock_promo_staging_cls,
        mock_bundle_staging_cls,
        mock_persist,
        mock_atomic,
    ) -> None:
        mock_atomic.return_value.__enter__ = MagicMock(return_value=None)
        mock_atomic.return_value.__exit__ = MagicMock(return_value=False)
        mock_persist.return_value = [uuid4()]
        mock_promo_staging_cls.return_value = self.staging
        mock_bundle_staging_cls.return_value = self.staging

        action_log = _action_log()
        self.staging.mark_promoted(
            self.bundle,
            action_log_id=str(action_log.pk),
        )

        from mobile_api.pod_capture.services.pod_capture_bundle_service import (
            PodCaptureBundleService,
        )
        from mobile_api.pod_capture.staging.evidence_promotion_service import (
            EvidencePromotionService,
        )

        bundles = PodCaptureBundleService(staging=self.staging)
        result = EvidencePromotionService(
            staging=self.staging,
            bundle_service=bundles,
        ).promote_staged_bundle(
            __import__(
                'mobile_api.pod_capture.dto.promotion_models',
                fromlist=['PodPromotionRequest'],
            ).PodPromotionRequest(
                bundle_id=self.bundle.bundle_id,
                action_log=action_log,
                scope=PodPromotionScope(
                    tenant_schema='tenant_a',
                    driver_id='drv-1',
                    shipment_id='ship-1',
                ),
            )
        )
        self.assertTrue(result.replayed)
        self.assertEqual(mock_persist.call_count, 0)

    def test_extract_bundle_id_aliases(self) -> None:
        self.assertEqual(
            extract_capture_bundle_id({'capture_bundle_id': 'b1'}),
            'b1',
        )
        self.assertEqual(
            extract_capture_bundle_id({'pod_capture_bundle_id': 'b2'}),
            'b2',
        )
