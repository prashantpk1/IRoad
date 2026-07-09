"""Support menu routes to standalone evidence capture."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from mobile_api.job_detail.projections.support_actions_projection import (
    build_job_support_actions,
    build_support_menu_action_row,
)
from mobile_api.helpers.action_navigation_metadata import (
    apply_standalone_evidence_capture_navigation_to_action_row,
    is_without_scope_action,
)


class SupportActionsProjectionTests(SimpleTestCase):
    def test_report_delay_routes_to_standalone_evidence(self):
        row = build_support_menu_action_row({
            'menu_key': 'report_delay',
            'label_en': 'Report Delay',
            'label_ar': 'Report Delay',
            'issue_type': 'delay',
            'severity': 'medium',
            'notes_placeholder': 'Delay notes',
        })
        self.assertEqual(row['action'], 'go_to_evidence_capture')
        self.assertEqual(row['screen'], 'evidence_capture')
        self.assertEqual(row['ui_mode'], 'standalone_evidence')
        self.assertFalse(row['linked_job_flow'])
        self.assertEqual(row['submit_contract']['type'], 'issue_report')
        self.assertTrue(row['requires_evidence_capture'])
        self.assertTrue(row['requires_gps'])

    def test_without_scope_action_detected(self):
        action = SimpleNamespace(
            action_code='OA-0017',
            action_scope='without',
            sequence_category='without',
            english_label='Incident Report',
        )
        self.assertTrue(is_without_scope_action(action))

    def test_standalone_navigation_for_without_scope(self):
        row = apply_standalone_evidence_capture_navigation_to_action_row(
            {
                'action_code': 'OA-0018',
                'execution_label': 'Cancel Movement',
                'execution_requirements': {'gps': False},
            },
            action=SimpleNamespace(
                action_code='OA-0018',
                action_scope='without',
                english_label='Cancel Movement',
            ),
        )
        self.assertEqual(row['ui_mode'], 'standalone_evidence')
        self.assertEqual(row['submit_contract']['type'], 'execute_action')
        self.assertEqual(
            row['submit_contract']['payload']['action_code'],
            'OA-0018',
        )

    def test_build_job_support_actions_movement_submit_contract(self):
        movement = SimpleNamespace(pk='mov-1', movement_id='mov-1')
        actions = build_job_support_actions(
            tenant_schema='',
            movement=movement,
        )
        self.assertEqual(len(actions), 3)
        payload = actions[0]['submit_contract']['payload']
        self.assertIn('movement_id', payload)
        self.assertNotIn('shipment_id', payload)

    def test_build_job_support_actions_includes_three_shortcuts(self):
        shipment = SimpleNamespace(pk='ship-1')
        actions = build_job_support_actions(
            tenant_schema='',
            shipment=shipment,
        )
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0]['menu_key'], 'report_delay')
        self.assertEqual(actions[1]['menu_key'], 'report_issue')
        self.assertEqual(actions[2]['menu_key'], 'request_dispatch_support')

    @patch(
        'mobile_api.job_detail.projections.support_actions_projection._iter_without_scope_actions',
    )
    def test_appends_tenant_without_scope_actions(self, mock_iter):
        mock_iter.return_value = [
            SimpleNamespace(
                action_code='OA-0017',
                english_label='Incident Report',
                action_scope='without',
                mobile_visible=True,
                sequence_number=1,
                arabic_label='',
                shipment_status_impact='',
                movement_status_impact='',
                sequence_category='without',
            ),
        ]
        shipment = SimpleNamespace(pk='ship-1')
        with patch(
            'mobile_api.job_detail.projections.support_actions_projection.project_allowed_action_row',
            return_value={
                'action_code': 'OA-0017',
                'action': 'go_to_evidence_capture',
                'ui_mode': 'standalone_evidence',
            },
        ):
            actions = build_job_support_actions(
                tenant_schema='tenant_a',
                shipment=shipment,
            )
        self.assertEqual(len(actions), 4)
        self.assertEqual(actions[3]['action_code'], 'OA-0017')
