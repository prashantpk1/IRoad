"""POD-section-only hard copy metadata tests."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.pod_capture.services.pod_section_metadata import (
    HARD_POD_ACTION_CODE,
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
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_default_pod_action',
        return_value=_mock_a7_action(),
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
    def test_hard_shipment_includes_confirmation_step(self, _mock_pages, _mock_dn, _mock_a7):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=3,
            pod_status=TenantShipment.PodStatus.PENDING,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        self.assertIn('hard_copy_confirmation', section['capture_steps'])
        self.assertTrue(section['hard_copy_confirmation']['required'])
        self.assertEqual(
            section['hard_copy_confirmation']['action_code'],
            HARD_POD_ACTION_CODE,
        )

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_default_pod_action',
        return_value=_mock_a7_action(),
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
    def test_hard_shipment_still_pending_after_digital_a7_compliant(self, _mock_pages, _mock_dn, _mock_a7):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=2,
            pod_status=TenantShipment.PodStatus.COMPLIANT,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        self.assertIn('hard_copy_confirmation', section['capture_steps'])
        self.assertTrue(section['hard_pod_pending'])
        self.assertTrue(section['hard_copy_confirmation']['required'])
        self.assertEqual(len(section['hard_copy_confirmation']['pages']), 1)

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_default_pod_action',
        return_value=_mock_a7_action(),
    )
    def test_digital_evidence_includes_optional_video_for_pod_capture(self, _mock_action):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=2,
            pod_status=TenantShipment.PodStatus.PENDING,
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
        self.assertTrue(reqs['photo'])
        self.assertTrue(reqs['video_optional'])
        self.assertEqual(reqs['video_max_count'], 1)
        self.assertEqual(reqs['video_max_duration_seconds'], 15)

    @patch(
        'mobile_api.pod_capture.services.pod_section_metadata.resolve_default_pod_action',
        return_value=_mock_a7_action(),
    )
    def test_soft_shipment_digital_only_steps(self, _mock_a7):
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.SOFT,
            pod_doc_count=0,
            pod_status=TenantShipment.PodStatus.PENDING,
            driver_id=uuid.uuid4(),
            driver=None,
        )
        section = build_pod_section_metadata(
            shipment,
            tenant_schema='tenant_test',
        )
        self.assertEqual(section['capture_steps'], ['digital_evidence'])
        self.assertFalse(section['hard_copy_confirmation']['required'])
