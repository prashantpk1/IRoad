"""
Foundation tests for POD capture staging (no workflow / kernel calls).
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from mobile_api.tests.transaction_test_case import TransactionTestCase

from mobile_api.pod_capture.dto.staging_models import PODCaptureBundleStatus
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.guards.pod_capture_security_guard import PodCaptureSecurityGuard
from mobile_api.pod_capture.services.pod_capture_orchestrator import PodCaptureOrchestrator
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


def _shipment_stub(*, shipment_id: str = 'ship-1', driver_id: str = 'drv-1') -> SimpleNamespace:
    updated = datetime(2026, 5, 26, 12, 0, 0, tzinfo=dt_timezone.utc)
    return SimpleNamespace(
        pk=shipment_id,
        shipment_id=shipment_id,
        shipment_no='SHP-001',
        driver_id=driver_id,
        booking_item_type='outbound',
        shipment_status='In Transit',
        updated_at=updated,
    )


class PodCaptureSecurityGuardTests(SimpleTestCase):
    def test_shipment_scoped_path_prefix(self) -> None:
        prefix = PodCaptureSecurityGuard.build_expected_upload_prefix(
            tenant_schema='tenant_a',
            driver_pk='drv-1',
            shipment_pk='ship-1',
        )
        self.assertEqual(
            prefix,
            'mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/',
        )

    @override_settings(MOBILE_POD_CAPTURE_ALLOW_ORPHAN_RETRY=False)
    def test_rejects_path_outside_prefix(self) -> None:
        from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
        from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput

        ctx = PodCaptureContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload={},
            client_capture_id='cap-orphan',
            media_items=[
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='tenant-uploads/other/photo.jpg',
                ),
            ],
        )
        guard = PodCaptureSecurityGuard(staging=EvidenceStagingService())
        with self.assertRaises(PodCaptureError) as raised:
            guard.validate_media_items(ctx)
        self.assertEqual(raised.exception.code, 'orphan_upload')


class PodCaptureOrchestratorTests(TransactionTestCase):
    def setUp(self) -> None:
        self.staging = EvidenceStagingService()
        self.orchestrator = PodCaptureOrchestrator(staging_service=self.staging)

    @patch('mobile_api.pod_capture.services.pod_capture_orchestrator.schema_context')
    @patch(
        'mobile_api.pod_capture.services.pod_capture_validation_service.PodCaptureValidationService.resolve_target_action'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_ownership_guard.resolve_shipment_job'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_security_guard.pod_capture_verify_media_storage'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_stale_guard.pod_capture_require_sync_metadata'
    )
    def test_capture_stages_bundle(
        self,
        mock_require_sync,
        mock_verify_storage,
        mock_resolve,
        mock_resolve_action,
        mock_schema,
    ) -> None:
        mock_require_sync.return_value = False
        mock_verify_storage.return_value = False
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=None)

        def _bind_action(ctx):
            ctx.operation_action = SimpleNamespace(
                action_code='POD_CAP',
                english_label='Capture POD',
                arabic_label='',
                auto_pod_post=True,
                hard_copy_collection=False,
                shipment_status_impact='',
                movement_status_impact='',
                booking_status_impact='',
            )

        mock_resolve_action.side_effect = _bind_action

        shipment = _shipment_stub()
        mock_resolve.return_value = SimpleNamespace(
            ownership_validated=True,
            shipment=shipment,
            booking=None,
            error_code=None,
            error_message=None,
        )

        driver = SimpleNamespace(
            pk='drv-1',
            driver_id='drv-1',
            driver_status='Active',
        )
        sync_token = shipment.updated_at.isoformat()
        payload = {
            'client_capture_id': 'cap-offline-001',
            'content_hash': sync_token,
            'workflow_version': sync_token,
            'target_action_code': 'POD_CAP',
            'pod_type': 'digital',
            'latitude': 25.0,
            'longitude': 55.0,
            'notes': 'POD delivered',
            'media': [
                {
                    'media_type': 'photo',
                    'file_ref': 'mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/photo.jpg',
                },
            ],
        }

        data = self.orchestrator.capture_pod_evidence(
            driver=driver,
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload=payload,
        )

        bundle = data['capture_bundle']
        self.assertEqual(bundle['status'], PODCaptureBundleStatus.READY.value)
        self.assertEqual(bundle['client_capture_id'], 'cap-offline-001')
        self.assertEqual(len(bundle['staged_media']), 1)
        self.assertTrue(bundle['promotion']['ready_for_execute'])
        self.assertTrue(data['next_step']['requires_execute_action'])
        self.assertIn('capture_bundle_id', bundle)

    @patch('mobile_api.pod_capture.services.pod_capture_orchestrator.schema_context')
    @patch(
        'mobile_api.pod_capture.services.pod_capture_validation_service.PodCaptureValidationService.resolve_target_action'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_ownership_guard.resolve_shipment_job'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_security_guard.pod_capture_verify_media_storage'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_stale_guard.pod_capture_require_sync_metadata'
    )
    def test_idempotent_replay_returns_same_bundle(
        self,
        mock_require_sync,
        mock_verify_storage,
        mock_resolve,
        mock_resolve_action,
        mock_schema,
    ) -> None:
        mock_require_sync.return_value = False
        mock_verify_storage.return_value = False
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=None)
        mock_resolve_action.side_effect = lambda ctx: setattr(
            ctx,
            'operation_action',
            SimpleNamespace(
                action_code='POD_CAP',
                english_label='Capture POD',
                arabic_label='',
                auto_pod_post=True,
                hard_copy_collection=False,
                shipment_status_impact='',
                movement_status_impact='',
                booking_status_impact='',
            ),
        )

        shipment = _shipment_stub()
        mock_resolve.return_value = SimpleNamespace(
            ownership_validated=True,
            shipment=shipment,
            booking=None,
            error_code=None,
            error_message=None,
        )

        driver = SimpleNamespace(
            pk='drv-1',
            driver_id='drv-1',
            driver_status='Active',
        )
        sync_token = shipment.updated_at.isoformat()
        payload = {
            'client_capture_id': 'cap-replay-001',
            'content_hash': sync_token,
            'workflow_version': sync_token,
            'target_action_code': 'POD_CAP',
            'pod_type': 'digital',
            'latitude': 25.0,
            'longitude': 55.0,
            'notes': 'POD',
            'media': [
                {
                    'media_type': 'photo',
                    'file_ref': 'mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/p1.jpg',
                },
            ],
        }

        first = self.orchestrator.capture_pod_evidence(
            driver=driver,
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload=payload,
        )
        second = self.orchestrator.capture_pod_evidence(
            driver=driver,
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload=payload,
        )

        self.assertEqual(
            first['capture_bundle']['capture_bundle_id'],
            second['capture_bundle']['capture_bundle_id'],
        )
        self.assertTrue(second['capture_bundle']['replayed'])

    def test_orchestrator_has_no_kernel_import(self) -> None:
        import mobile_api.pod_capture.services.pod_capture_orchestrator as orch_mod

        source = open(orch_mod.__file__, encoding='utf-8').read()
        self.assertNotIn(
            'from iroad_tenants.services.action_execution_service',
            source,
        )
        self.assertNotIn('apply_execution_side_effects', source)


class EvidencePromotionServiceTests(SimpleTestCase):
    def test_orchestrator_does_not_promote(self) -> None:
        import mobile_api.pod_capture.services.pod_capture_orchestrator as orch_mod

        source = open(orch_mod.__file__, encoding='utf-8').read()
        self.assertNotIn(
            'from mobile_api.pod_capture.staging.evidence_promotion_service import',
            source,
        )
        self.assertNotIn('promote_staged_bundle', source)
        self.assertNotIn('persist_pod_action_log_media', source)
