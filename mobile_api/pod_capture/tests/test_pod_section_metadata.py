"""POD-section-only hard copy metadata tests."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.pod_capture.services.pod_section_metadata import (
    HARD_COPY_SCREEN_TITLE,
    HARD_POD_ACTION_CODE,
    UI_MODE_HARD_POD_CONFIRMATION,
    build_hard_copy_confirmation_ui,
    build_pod_section_metadata,
)
from tenant_workspace.models import TenantShipment


def _mock_a7_action():
    return SimpleNamespace(
        action_code='A7',
        english_label='Upload POD',
        auto_pod_post=True,
        hard_copy_collection=False,
        movement_status_impact='',
        booking_status_impact='',
        shipment_status_impact='POD_Submitted',
    )


class PodSectionMetadataTests(TestCase):
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_digital_pod_action',
        return_value=_mock_a7_action(),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='A7H', hard_copy_collection=True),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata._shipment_has_delivery_note',
        return_value=True,
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.build_hard_pod_confirmation_context',
        return_value={
            'documents': [{'document_id': 'doc-1', 'record_no': 'REC-1', 'pages': []}],
            'pages': [{'label': 'IMG-(ABC-001)', 'page_id': '1'}],
        },
    )
    def test_hard_shipment_includes_confirmation_step(
        self,
        _mock_pages,
        _mock_dn,
        _mock_hard,
        _mock_a7,
    ):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=3,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
            log_evidence={'pod_uploaded': True},
        )
        self.assertIn('hard_copy_confirmation', section['capture_steps'])
        self.assertTrue(section['hard_copy_confirmation']['required'])
        self.assertEqual(
            section['hard_copy_confirmation']['action_code'],
            HARD_POD_ACTION_CODE,
        )
        hard_block = section['hard_copy_confirmation']
        self.assertEqual(hard_block['screen_title'], HARD_COPY_SCREEN_TITLE)
        self.assertEqual(hard_block['ui_mode'], UI_MODE_HARD_POD_CONFIRMATION)
        confirmation_ui = hard_block['confirmation_ui']
        self.assertEqual(confirmation_ui['screen_title'], HARD_COPY_SCREEN_TITLE)
        self.assertEqual(confirmation_ui['ui_mode'], UI_MODE_HARD_POD_CONFIRMATION)
        self.assertEqual(confirmation_ui['primary_button']['label'], 'Submit POD')
        self.assertFalse(confirmation_ui['requires_photo'])
        self.assertEqual(len(confirmation_ui['checklist']), 1)
        self.assertEqual(confirmation_ui['checklist'][0]['label'], 'IMG-(ABC-001)')

    def test_build_hard_copy_confirmation_ui_checklist_contract(self):
        ui = build_hard_copy_confirmation_ui(
            [
                {'label': 'IMG-(ABC-002)', 'line_no': 1, 'page_id': 'p1'},
                {'label': 'IMG-(ABC-003)', 'physical_page_no': 3, 'page_id': 'p2'},
            ],
        )
        self.assertEqual(ui['screen_title'], HARD_COPY_SCREEN_TITLE)
        self.assertEqual(ui['info_banner']['title'], 'Physical Custody Confirmation')
        self.assertEqual(len(ui['checklist']), 2)
        self.assertIn('physical receipt', ui['checklist'][1]['confirmation_text'])

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_digital_pod_action',
        return_value=_mock_a7_action(),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='A7H', hard_copy_collection=True),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata._shipment_has_delivery_note',
        return_value=True,
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.build_hard_pod_confirmation_context',
        return_value={
            'documents': [{'document_id': 'doc-1', 'record_no': 'REC-22', 'pages': []}],
            'pages': [{'label': 'DN-1020', 'page_id': '1'}],
        },
    )
    def test_hard_shipment_still_pending_after_digital_a7_compliant(
        self,
        _mock_pages,
        _mock_dn,
        _mock_hard,
        _mock_a7,
    ):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=2,
            pod_status=TenantShipment.PodStatus.COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
            log_evidence={'pod_uploaded': True},
        )
        self.assertIn('hard_copy_confirmation', section['capture_steps'])
        self.assertTrue(section['hard_pod_pending'])
        self.assertTrue(section['hard_copy_confirmation']['required'])
        self.assertEqual(len(section['hard_copy_confirmation']['pages']), 1)

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_digital_pod_action',
        return_value=_mock_a7_action(),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='A7H', hard_copy_collection=True),
    )
    def test_digital_evidence_includes_required_video_for_pod_capture(
        self,
        _mock_hard,
        _mock_action,
    ):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.SOFT,
            pod_doc_count=2,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        digital = section['digital_evidence']
        self.assertEqual(digital['action_code'], 'A7')
        reqs = digital['requirements']
        self.assertTrue(reqs['photo_enabled'])
        self.assertFalse(reqs['photo'])
        self.assertFalse(reqs['signature'])
        self.assertTrue(reqs['video_enabled'])
        self.assertFalse(reqs['video'])
        self.assertTrue(reqs['video_optional'])
        self.assertEqual(reqs['video_min_count'], 0)
        self.assertEqual(reqs['video_max_count'], 1)
        self.assertEqual(reqs['video_max_duration_seconds'], 60)
        media_types = [row['media_type'] for row in digital['media_steps']]
        self.assertEqual(media_types, ['photo', 'video'])
        video_step = digital['media_steps'][-1]
        self.assertFalse(video_step['required'])
        self.assertEqual(video_step['max_duration_seconds'], 60)
        self.assertEqual(section['screen_title'], 'Capturing Action Evidences')
        capture_ui = section['capture_ui']
        self.assertEqual(capture_ui['screen_title'], 'Capturing Action Evidences')
        self.assertEqual(capture_ui['primary_button']['label'], 'Next')
        self.assertEqual(capture_ui['primary_button']['action'], 'submit_digital_evidence')
        self.assertTrue(capture_ui['primary_button']['complete_upload_after_execute'])
        section_ids = [row['id'] for row in capture_ui['sections']]
        self.assertEqual(section_ids, ['evidence_photos', 'evidence_video', 'note'])

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_digital_pod_action',
        return_value=_mock_a7_action(),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='A7H', hard_copy_collection=True),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata._shipment_has_delivery_note',
        return_value=True,
    )
    def test_hard_shipment_at_delivery_includes_wizard_steps_before_a7(
        self,
        _mock_dn,
        _mock_hard,
        _mock_a7,
    ):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=1,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        self.assertEqual(
            section['capture_steps'],
            ['digital_evidence', 'hard_copy_confirmation'],
        )
        hard = section['hard_copy_confirmation']
        self.assertTrue(hard['applicable'])
        self.assertFalse(hard['actionable'])
        self.assertFalse(hard['submit_allowed'])
        digital_ui = section['digital_evidence']['capture_ui']
        self.assertEqual(digital_ui['primary_button']['wizard_next_step'], 'hard_copy_confirmation')
        self.assertFalse(digital_ui['primary_button']['complete_upload_after_execute'])

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_digital_pod_action',
        return_value=_mock_a7_action(),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='A7H', hard_copy_collection=True),
    )
    def test_soft_shipment_digital_only_steps(self, _mock_hard, _mock_a7):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.SOFT,
            pod_doc_count=0,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        self.assertEqual(section['capture_steps'], ['digital_evidence'])
        self.assertFalse(section['hard_copy_confirmation']['required'])

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_digital_pod_action',
        return_value=_mock_a7_action(),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_hard_copy_pod_action',
        return_value=SimpleNamespace(action_code='A7H', hard_copy_collection=True),
    )
    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata._shipment_has_delivery_note',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_field_catalog.operation_shipment_uses_hard_copy_pod',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action.portal_shipment_document_exists',
        return_value=False,
    )
    def test_hard_shipment_without_portal_document_blocks_digital_next(
        self,
        _mock_portal,
        _mock_hard_pod,
        _mock_dn,
        _mock_hard,
        _mock_a7,
    ):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=0,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        hard = section['hard_copy_confirmation']
        self.assertFalse(hard['applicable'])
        self.assertFalse(hard['actionable'])
        digital_ui = section['digital_evidence']['capture_ui']
        self.assertNotIn('wizard_next_step', digital_ui['primary_button'])
        self.assertTrue(digital_ui['primary_button']['complete_upload_after_execute'])
        self.assertTrue(digital_ui['primary_button'].get('hard_copy_blocked'))
        section_ui = section['capture_ui']
        self.assertTrue(section_ui.get('submit_blocked'))
        self.assertIn('Shipment Document', section_ui.get('submit_blocked_reason', ''))
