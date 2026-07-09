"""Tests for mobile Action Master evidence metadata projection."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.helpers.action_execution_metadata import (
    build_execution_requirements,
    project_allowed_action_row,
)


def _action(**kwargs):
    base = {
        'action_id': '00000000-0000-0000-0000-000000000001',
        'action_code': 'OA-0008',
        'english_label': 'POD',
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'movement_status_impact': '',
        'booking_status_impact': '',
        'shipment_status_impact': '',
        'sequence_number': 8,
        'action_scope': 'job',
        'sequence_category': '',
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class ActionExecutionMetadataTests(TestCase):
    def test_auto_pod_post_optional_photo_video_via_pod_policy(self):
        req = build_execution_requirements(
            _action(auto_pod_post=True),
        )
        self.assertTrue(req['photo_enabled'])
        self.assertEqual(req['photo_min_count'], 0)
        self.assertFalse(req['photo'])
        self.assertTrue(req['video_enabled'])
        self.assertEqual(req['video_min_count'], 0)
        self.assertFalse(req['video'])
        self.assertTrue(req['video_optional'])

    def test_hard_pod_action_uses_custody_flow_not_photo_evidence(self):
        req = build_execution_requirements(
            _action(
                action_code='OA-HARD',
                english_label='Hard POD Collection',
                hard_copy_collection=True,
            ),
        )
        self.assertFalse(req['photo'])
        self.assertFalse(req['gps'])
        self.assertFalse(req['video'])
        self.assertTrue(req['hard_copy_collection'])
        self.assertTrue(req['custody_submission_required'])
        self.assertEqual(req['capture_mode'], 'hard_copy_confirmation')

    def test_unloading_row_routes_to_evidence_capture(self):
        row = project_allowed_action_row(
            _action(
                action_code='OA-0007',
                english_label='Start Unloading',
                movement_status_impact='Completed',
            ),
        )
        self.assertEqual(row['action'], 'go_to_evidence_capture')
        self.assertEqual(row['screen'], 'evidence_capture')
        self.assertTrue(row['requires_evidence_capture'])
        self.assertFalse(row['direct_execute'])
        self.assertFalse(row['requires_photo'])
        self.assertFalse(row['requires_video'])
        self.assertTrue(row['show_photo'])
        self.assertTrue(row['show_video'])
        self.assertTrue(row['allow_submit_without_media'])
        self.assertTrue(row['capture_ui']['allow_submit_without_media'])
        self.assertFalse(row['capture_ui']['submit_validation']['photo_required'])

    def test_oa_0010_job_closed_routes_to_evidence_capture(self):
        action = _action(
            action_code='OA-0010',
            english_label='Job Closed',
            booking_status_impact='Executed',
            shipment_status_impact='Closed',
            sequence_number=10,
        )
        req = build_execution_requirements(action)
        self.assertFalse(req['direct_execute'])
        self.assertTrue(req['requires_evidence_capture'])
        self.assertEqual(req['photo_min_count'], 0)

        row = project_allowed_action_row(action)
        self.assertEqual(row['action'], 'go_to_evidence_capture')
        self.assertEqual(row['screen'], 'evidence_capture')
        self.assertEqual(row.get('ui_mode'), 'job_close')
        self.assertFalse(row.get('direct_execute'))
        self.assertFalse(row['requires_photo'])
        self.assertTrue(row['show_photo'])

    def test_oa_0009_primary_action_routes_to_collect_payment_screen(self):
        from decimal import Decimal
        from unittest.mock import MagicMock

        action = _action(
            action_code='OA-0009',
            english_label='Collect Payment',
            auto_treasury_post=True,
            sequence_number=9,
        )
        shipment = MagicMock()
        shipment.order_type = 'COD'
        shipment.cod_amount = Decimal('1500.00')
        row = project_allowed_action_row(
            action,
            shipment=shipment,
            tenant_schema='tenant_a',
        )
        self.assertEqual(row['action'], 'go_to_payment_collection')
        self.assertEqual(row['screen'], 'collect_payment')
        self.assertEqual(row['action_code'], 'OA-0009')
        self.assertEqual(
            row['payment_collect_endpoint'],
            '/api/v1/mobile/driver/payments/collect/',
        )
        self.assertFalse(row.get('direct_execute'))

    def test_collect_payment_note_not_required(self):
        req = build_execution_requirements(
            _action(
                action_code='OA-0009',
                english_label='Collect Payment',
                auto_treasury_post=True,
                sequence_number=9,
            ),
        )
        self.assertFalse(req['note_required'])

    def test_combined_pod_row_uses_tenant_action_code_in_capture_ui(self):
        row = project_allowed_action_row(
            _action(
                action_code='OA-0008',
                english_label='POD',
                auto_pod_post=True,
                hard_copy_collection=True,
            ),
            tenant_schema='tenant_test',
        )
        capture_ui = row['capture_ui']
        button = capture_ui['primary_button']
        self.assertEqual(button['execute_action_code'], 'OA-0008')
        self.assertEqual(button['wizard_next_step'], 'hard_copy_confirmation')
        self.assertFalse(button['complete_upload_after_execute'])

    def test_label_only_pod_routes_to_pod_capture_with_capture_ui(self):
        row = project_allowed_action_row(
            _action(
                action_code='OA-0009',
                english_label='POD',
                sequence_number=9,
            ),
            tenant_schema='tenant_test',
        )
        self.assertEqual(row['action'], 'go_to_pod_capture')
        self.assertEqual(row['screen'], 'pod_capture')
        self.assertIn('primary_button', row['capture_ui'])

    def test_oa_0001_start_job_routes_to_evidence_capture(self):
        action = _action(
            action_code='OA-0001',
            english_label='Start Job',
            booking_status_impact='In_Execution',
            sequence_number=1,
        )
        req = build_execution_requirements(action)
        self.assertTrue(req['requires_evidence_capture'])
        self.assertEqual(req['photo_min_count'], 0)
        self.assertEqual(req['video_min_count'], 0)

        row = project_allowed_action_row(action)
        self.assertEqual(row['action'], 'go_to_evidence_capture')
        self.assertEqual(row['screen'], 'evidence_capture')
        self.assertTrue(row['requires_evidence_capture'])
        self.assertFalse(row.get('direct_execute'))
        self.assertFalse(row['requires_photo'])
        self.assertTrue(row['show_photo'])
        self.assertTrue(row['show_video'])

    def test_empty_move_catalog_action_routes_to_evidence_capture(self):
        action = _action(
            action_code='OA-0014',
            english_label='Start Movement',
            sequence_category='empty_move',
            sequence_number=1,
        )
        row = project_allowed_action_row(action)
        self.assertEqual(row['action'], 'go_to_evidence_capture')
        self.assertEqual(row['screen'], 'evidence_capture')
        self.assertEqual(row['ui_mode'], 'empty_move')
        self.assertTrue(row['requires_evidence_capture'])
        self.assertTrue(row.get('capture_ui'))
