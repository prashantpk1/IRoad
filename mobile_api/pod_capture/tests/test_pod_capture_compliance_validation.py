"""
Enterprise POD compliance validation and canonical action registry tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    PodActionRole,
    action_has_role,
    classify_pod_action_role,
    is_delivered_status_action,
    is_pod_upload_action,
    is_unloading_action,
)
from mobile_api.pod_capture.policy.compliance_log_evidence import log_evidence_flags
from mobile_api.pod_capture.policy.pod_capture_policy import build_pod_capture_requirements
from mobile_api.pod_capture.services.pod_capture_validation_service import (
    PodCaptureValidationService,
)


def _action(
    *,
    code: str = 'A7',
    label: str = 'Upload POD',
    shipment_impact: str = '',
    auto_pod: bool = False,
    hard_copy: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        action_code=code,
        english_label=label,
        arabic_label='',
        auto_pod_post=auto_pod,
        hard_copy_collection=hard_copy,
        shipment_status_impact=shipment_impact,
        movement_status_impact='',
        booking_status_impact='',
    )


class CanonicalPodActionRegistryTests(SimpleTestCase):
    def test_a7_maps_to_pod_upload_not_delivered(self) -> None:
        a7 = _action(code='A7', label='Upload POD')
        self.assertTrue(is_pod_upload_action(a7))
        self.assertFalse(is_delivered_status_action(a7))
        self.assertEqual(classify_pod_action_role(a7), PodActionRole.POD_UPLOAD)

    def test_a8_maps_to_unloading_not_pod_upload(self) -> None:
        a8 = _action(code='A8', label='Unloading')
        self.assertTrue(is_unloading_action(a8))
        self.assertFalse(is_pod_upload_action(a8))
        self.assertEqual(classify_pod_action_role(a8), PodActionRole.UNLOADING)

    def test_delivered_uses_status_impact_not_a7(self) -> None:
        delivered = _action(code='DEL', label='Mark Delivered', shipment_impact='Delivered')
        self.assertTrue(is_delivered_status_action(delivered))
        self.assertFalse(is_pod_upload_action(delivered))
        self.assertEqual(classify_pod_action_role(delivered), PodActionRole.DELIVERED_STATUS)

    def test_log_evidence_flags_fixed_mapping(self) -> None:
        a7 = _action(code='A7', label='Upload POD')
        a8 = _action(code='A8', label='Unloading')
        delivered = _action(code='DEL', label='Delivered', shipment_impact='Delivered')
        flags = log_evidence_flags(
            [
                SimpleNamespace(operation_action=a7),
                SimpleNamespace(operation_action=a8),
                SimpleNamespace(operation_action=delivered),
            ]
        )
        self.assertTrue(flags['pod_uploaded'])
        self.assertTrue(flags['delivered_log'])
        self.assertFalse(action_has_role(a8, PodActionRole.POD_UPLOAD))


class PodCapturePolicyTests(SimpleTestCase):
    def test_signature_type_requires_signature(self) -> None:
        action = _action(code='A7', label='Upload POD')
        req = build_pod_capture_requirements(
            action,
            pod_capture_type='signature',
        )
        self.assertTrue(req.get('signature'))

    def test_multi_page_uses_shipment_doc_count(self) -> None:
        action = _action(code='A7', label='Upload POD')
        shipment = SimpleNamespace(pod_doc_count=3)
        req = build_pod_capture_requirements(
            action,
            pod_capture_type='multi_page',
            shipment=shipment,
        )
        self.assertGreaterEqual(int(req.get('document_min_count') or 0), 3)

    def test_invalid_pod_type_empty_overlay(self) -> None:
        from mobile_api.pod_capture.policy.pod_capture_policy import derive_pod_type_overlay

        self.assertEqual(derive_pod_type_overlay('invalid_type'), {})

    def test_digital_pod_requires_photo_signature_and_video(self) -> None:
        action = _action(code='A7', label='Upload POD', auto_pod=True)
        req = build_pod_capture_requirements(
            action,
            pod_capture_type='digital',
        )
        self.assertTrue(req.get('photo'))
        self.assertTrue(req.get('signature'))
        self.assertTrue(req.get('video'))
        self.assertEqual(int(req.get('video_min_count') or 0), 1)
        self.assertFalse(req.get('video_optional'))


class PodCaptureValidationServiceTests(SimpleTestCase):
    def setUp(self) -> None:
        self.validator = PodCaptureValidationService()

    def _context(self, **overrides) -> PodCaptureContext:
        base = {
            'driver': SimpleNamespace(pk='drv-1', driver_id='drv-1', driver_status='Active'),
            'tenant_schema': 'tenant_a',
            'shipment_id': 'ship-1',
            'payload': {},
            'client_capture_id': 'cap-1',
            'content_hash': 'hash-1',
            'target_action_code': 'A7',
            'pod_capture_type': 'digital',
            'latitude': '25.0',
            'longitude': '55.0',
            'notes': 'delivered ok',
            'media_items': [
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/p.jpg',
                ),
            ],
            'shipment': SimpleNamespace(
                pk='ship-1',
                driver_id='drv-1',
                pod_doc_count=1,
                shipment_status='In Transit',
            ),
        }
        base.update(overrides)
        return PodCaptureContext(**base)

    @patch.object(PodCaptureValidationService, 'resolve_target_action')
    def test_missing_gps_when_required(self, mock_resolve) -> None:
        mock_resolve.return_value = None
        action = _action(code='A7', label='Upload POD')
        ctx = self._context(latitude='', longitude='', operation_action=action)
        ctx.compliance_requirements = build_pod_capture_requirements(
            action,
            pod_capture_type='digital',
        )
        with patch.object(
            self.validator._evidence,
            '_validate_gps',
            side_effect=ExecuteActionError(
                'gps',
                code='gps_required',
                http_status=400,
                message_key='mobile.jobs.execute.gps_required',
            ),
        ):
            with patch.object(self.validator._evidence, '_validate_notes'):
                with patch.object(self.validator._evidence, '_validate_media'):
                    with self.assertRaises(PodCaptureError) as exc:
                        self.validator.validate_pod_compliance(ctx)
        self.assertEqual(exc.exception.code, 'gps_required')

    @patch.object(PodCaptureValidationService, 'resolve_target_action')
    def test_missing_signature_for_signature_pod(self, mock_resolve) -> None:
        mock_resolve.return_value = None
        action = _action(code='A7', label='Upload POD')
        ctx = self._context(
            operation_action=action,
            pod_capture_type='signature',
            media_items=[
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/p.jpg',
                ),
            ],
        )
        with self.assertRaises(PodCaptureError) as exc:
            self.validator.validate_pod_compliance(ctx)
        self.assertEqual(exc.exception.code, 'signature_required')

    def test_duplicate_media_rejected(self) -> None:
        ctx = self._context(
            operation_action=_action(code='A7', label='Upload POD'),
            media_items=[
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/same.jpg',
                ),
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/same.jpg',
                ),
            ],
        )
        ctx.compliance_requirements = {'photo_min_count': 0}
        with patch.object(self.validator._evidence, '_validate_gps'):
            with patch.object(self.validator._evidence, '_validate_notes'):
                with patch.object(self.validator._evidence, '_validate_media'):
                    with self.assertRaises(PodCaptureError) as exc:
                        self.validator.validate_pod_compliance(ctx)
        self.assertEqual(exc.exception.code, 'duplicate_media')

    def test_invalid_pod_capture_type_on_metadata(self) -> None:
        ctx = self._context(pod_capture_type='invalid_type')
        with self.assertRaises(PodCaptureError) as exc:
            self.validator.validate_capture_request(ctx)
        self.assertEqual(exc.exception.code, 'invalid_pod_capture_type')

    @patch(
        'mobile_api.pod_capture.staging.evidence_staging_service.EvidenceStagingService.assert_file_ref_uploadable'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_security_guard.pod_capture_verify_media_storage'
    )
    def test_invalid_mime_rejected_by_security_guard(self, mock_verify, mock_file_ref) -> None:
        from mobile_api.pod_capture.guards.pod_capture_security_guard import (
            PodCaptureSecurityGuard,
        )
        from mobile_api.pod_capture.staging.evidence_staging_service import (
            EvidenceStagingService,
        )

        mock_verify.return_value = False
        mock_file_ref.return_value = None
        guard = PodCaptureSecurityGuard(staging=EvidenceStagingService())
        ctx = self._context(
            client_capture_id='cap-mime',
            media_items=[
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/file.exe',
                ),
            ],
        )
        with self.assertRaises(PodCaptureError) as exc:
            guard.validate_media_items(ctx)
        self.assertEqual(exc.exception.code, 'media_extension_not_allowed')

    @patch(
        'mobile_api.pod_capture.staging.evidence_staging_service.EvidenceStagingService.assert_file_ref_uploadable'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_security_guard.ExecutionMediaSecurityService._assert_storage_object'
    )
    @patch(
        'mobile_api.pod_capture.guards.pod_capture_security_guard.pod_capture_verify_media_storage'
    )
    def test_oversized_upload_rejected(self, mock_verify, mock_size, mock_file_ref) -> None:
        from mobile_api.pod_capture.guards.pod_capture_security_guard import (
            PodCaptureSecurityGuard,
        )
        from mobile_api.pod_capture.staging.evidence_staging_service import (
            EvidenceStagingService,
        )

        mock_verify.return_value = True
        mock_file_ref.return_value = None
        mock_size.side_effect = ExecuteActionError(
            'too big',
            code='media_file_too_large',
            http_status=400,
            message_key='mobile.jobs.execute.media_file_too_large',
        )
        guard = PodCaptureSecurityGuard(staging=EvidenceStagingService())
        ctx = self._context(
            client_capture_id='cap-size',
            media_items=[
                PODCaptureMediaItemInput(
                    media_type='photo',
                    file_ref='mobile_driver_uploads/tenant_a/drv-1/ship-1/pod_capture/big.jpg',
                ),
            ],
        )
        with self.assertRaises(PodCaptureError) as exc:
            guard.validate_media_items(ctx)
        self.assertEqual(exc.exception.code, 'media_file_too_large')
