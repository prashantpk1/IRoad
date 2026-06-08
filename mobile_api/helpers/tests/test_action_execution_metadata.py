"""Tests for mobile Action Master evidence metadata projection."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.helpers.action_execution_metadata import build_execution_requirements


def _action(**kwargs):
    base = {
        'action_code': 'A7',
        'english_label': 'Upload POD',
        'auto_pod_post': False,
        'hard_copy_collection': False,
        'movement_status_impact': '',
        'booking_status_impact': '',
        'shipment_status_impact': '',
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
