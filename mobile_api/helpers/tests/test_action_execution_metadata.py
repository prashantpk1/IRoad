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
        'action_code': 'A7',
        'english_label': 'Upload POD',
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'movement_status_impact': '',
        'booking_status_impact': '',
        'shipment_status_impact': '',
        'sequence_number': 7,
        'action_scope': 'job',
        'sequence_category': '',
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class ActionExecutionMetadataTests(TestCase):
    def test_auto_pod_post_requires_photo_video_optional(self):
        req = build_execution_requirements(
            _action(auto_pod_post=True),
        )
        self.assertTrue(req['photo'])
        self.assertGreaterEqual(req['photo_min_count'], 1)
        self.assertFalse(req['video'])
        self.assertEqual(req['video_min_count'], 0)
        self.assertTrue(req['video_optional'])

    def test_hard_pod_action_uses_custody_flow_not_photo_evidence(self):
        req = build_execution_requirements(
            _action(
                action_code='A7H',
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

    def test_a8_row_never_routes_to_pod_capture(self):
        row = project_allowed_action_row(
            _action(
                action_code='A8',
                english_label='Unloading Completed',
                movement_status_impact='Completed',
            ),
        )
        self.assertEqual(row['action'], 'execute_action')
        self.assertEqual(row['screen'], 'job_detail')
        self.assertFalse(row['requires_photo'])
        self.assertNotIn('capture_ui', row)
        self.assertEqual(row['execution_requirements']['photo'], False)

    def test_a10_job_closed_has_no_capture_requirements(self):
        action = _action(
            action_code='A10',
            english_label='Job Closed',
            booking_status_impact='Executed',
            shipment_status_impact='Closed',
            sequence_number=10,
        )
        req = build_execution_requirements(action)
        self.assertFalse(req['gps'])
        self.assertFalse(req['photo'])
        self.assertFalse(req['video'])
        self.assertFalse(req['note'])
        self.assertEqual(req['photo_min_count'], 0)
        self.assertEqual(req['shipment_status_impact'], 'Closed')

        row = project_allowed_action_row(action)
        self.assertFalse(row['requires_gps'])
        self.assertFalse(row['requires_photo'])
        self.assertFalse(row['requires_video'])
        self.assertFalse(row['requires_note'])
        self.assertFalse(row['execution_requirements']['gps'])
        self.assertFalse(row['execution_requirements']['note'])

    def test_a9_note_not_required(self):
        req = build_execution_requirements(
            _action(
                action_code='A9',
                english_label='Collect Payment',
                auto_treasury_post=True,
                sequence_number=9,
            ),
        )
        self.assertFalse(req['note_required'])

    def test_a1_start_job_has_no_capture_requirements(self):
        action = _action(
            action_code='A1',
            english_label='Start Job',
            booking_status_impact='In_Execution',
            sequence_number=1,
        )
        req = build_execution_requirements(action)
        self.assertFalse(req['gps'])
        self.assertFalse(req['photo'])
        self.assertFalse(req['video'])
        self.assertFalse(req['note'])

        row = project_allowed_action_row(action)
        self.assertFalse(row['requires_gps'])
        self.assertFalse(row['requires_photo'])
        self.assertFalse(row['requires_video'])
        self.assertFalse(row['requires_note'])
