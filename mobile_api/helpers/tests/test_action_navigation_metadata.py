"""Hard POD navigation metadata tests."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.helpers.action_navigation_metadata import (
    apply_hard_copy_navigation_to_action_row,
    enrich_timeline_event_navigation,
)
from tenant_workspace.models import TenantShipment


class ActionNavigationMetadataTests(TestCase):
    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
        return_value={
            'required': True,
            'pending': True,
            'action_code': 'A7H',
            'pages': [{'label': 'Page 1', 'page_id': '1'}],
            'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
            'execute_action_code': 'A7H',
        },
    )
    def test_timeline_pending_hard_pod_includes_checklist_screen(self, _mock_block):
        action = SimpleNamespace(
            action_code='A7H',
            hard_copy_collection=True,
            english_label='Hard POD Collection',
        )
        shipment = SimpleNamespace(
            pk=uuid.uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=2,
        )
        event = enrich_timeline_event_navigation(
            {'action_code': 'A7H', 'event_type': 'hard_pod', 'timeline_state': 'pending'},
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
        )
        self.assertEqual(event['screen'], 'pod_capture')
        self.assertEqual(event['action'], 'go_to_pod_capture')
        self.assertEqual(event['capture_mode'], 'hard_copy_confirmation')
        self.assertTrue(event['hard_copy_confirmation']['required'])
        self.assertEqual(len(event['hard_copy_confirmation']['pages']), 1)

    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
        return_value={
            'required': True,
            'pending': True,
            'action_code': 'A7H',
            'pages': [],
            'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
            'execute_action_code': 'A7H',
        },
    )
    def test_allowed_action_row_clears_photo_gps_flags(self, _mock_block):
        action = SimpleNamespace(action_code='A7H', hard_copy_collection=True)
        row = apply_hard_copy_navigation_to_action_row(
            {
                'action_code': 'A7H',
                'requires_gps': True,
                'requires_photo': True,
                'execution_requirements': {'gps': True, 'photo': True},
            },
            action,
            shipment=SimpleNamespace(pk=uuid.uuid4(), pod_type='Hard'),
            tenant_schema='tenant_a',
        )
        self.assertFalse(row['requires_gps'])
        self.assertFalse(row['requires_photo'])
        self.assertTrue(row['execution_requirements']['custody_submission_required'])
