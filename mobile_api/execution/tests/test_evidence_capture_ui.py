"""Tests for generic evidence capture UI contract."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.execution.evidence.evidence_capture_ui import (
    build_generic_evidence_capture_ui,
    build_standalone_evidence_capture_ui,
)


class EvidenceCaptureUiTests(SimpleTestCase):
    def test_start_job_optional_photo_video_sections(self):
        ui = build_generic_evidence_capture_ui(
            {
                'photo_enabled': True,
                'video_enabled': True,
                'photo_min_count': 0,
                'video_min_count': 0,
                'note': False,
            },
            action_code='OA-0001',
            screen_title='Start Job',
        )
        photo = ui['sections'][0]
        video = ui['sections'][1]
        self.assertFalse(photo['required'])
        self.assertTrue(photo['optional'])
        self.assertEqual(photo['min_count'], 0)
        self.assertFalse(video['required'])
        self.assertTrue(video['optional'])
        self.assertEqual(video['min_count'], 0)
        self.assertEqual(ui['primary_button']['execute_action_code'], 'OA-0001')
        self.assertTrue(ui['allow_submit_without_media'])
        self.assertTrue(ui['primary_button']['allow_empty_media'])

    def test_optional_photo_and_video_max_15_seconds(self):
        ui = build_generic_evidence_capture_ui(
            {'photo_min_count': 2, 'video_min_count': 1},
            action_code='OA-0002',
        )
        photo = next(s for s in ui['sections'] if s['media_type'] == 'photo')
        video = next(s for s in ui['sections'] if s['media_type'] == 'video')
        self.assertFalse(photo['required'])
        self.assertTrue(photo['optional'])
        self.assertEqual(photo['min_count'], 0)
        self.assertFalse(video['required'])
        self.assertTrue(video['optional'])
        self.assertEqual(video['min_count'], 0)
        self.assertFalse(ui['requires_photo'])
        self.assertFalse(ui['requires_video'])
        self.assertTrue(ui['photo_optional'])
        self.assertTrue(ui['video_optional'])
        self.assertFalse(ui['submit_validation']['photo_required'])
        self.assertFalse(ui['submit_validation']['video_required'])

    def test_optional_video_max_60_seconds(self):
        ui = build_generic_evidence_capture_ui(
            {'photo_min_count': 0, 'video_min_count': 0},
            action_code='OA-0002',
        )
        video = next(s for s in ui['sections'] if s['media_type'] == 'video')
        self.assertFalse(video['required'])
        self.assertTrue(video['optional'])
        self.assertEqual(video['min_count'], 0)
        self.assertEqual(video['max_count'], 1)
        self.assertEqual(video['max_duration_seconds'], 60)
        self.assertEqual(ui['submit_validation']['video_max_duration_seconds'], 60)
        self.assertFalse(ui['submit_validation']['video_required'])

    def test_sparse_requirements_still_show_photo_video_sections(self):
        ui = build_generic_evidence_capture_ui(
            {'direct_execute': True},
            action_code='OA-0006',
        )
        media_types = [s['media_type'] for s in ui['sections']]
        self.assertEqual(media_types[:2], ['photo', 'video'])
        self.assertIn('note', media_types)
        self.assertTrue(ui['show_photo'])
        self.assertTrue(ui['show_video'])
        self.assertTrue(ui['allow_submit_without_media'])

    def test_pickup_arrival_navigation_includes_capture_ui(self):
        from types import SimpleNamespace

        from mobile_api.helpers.action_execution_metadata import project_allowed_action_row

        row = project_allowed_action_row(
            SimpleNamespace(
                action_id='00000000-0000-0000-0000-000000000002',
                action_code='OA-0002',
                english_label='Pickup Arrival',
                arabic_label='',
                auto_pod_post=False,
                hard_copy_collection=False,
                movement_status_impact='At Pickup',
                booking_status_impact='',
                shipment_status_impact='',
                sequence_number=2,
                action_scope='job',
                sequence_category='',
            ),
        )
        capture_ui = row['capture_ui']
        photo = next(s for s in capture_ui['sections'] if s['media_type'] == 'photo')
        self.assertFalse(photo['required'])
        self.assertEqual(photo['min_count'], 0)

    def test_standalone_evidence_capture_ui(self):
        ui = build_standalone_evidence_capture_ui(
            {'gps': True, 'photo_min_count': 0, 'video_min_count': 0, 'allow_submit_without_media': True},
            screen_title='Report Delay',
            submit_button_label='Submit Report',
        )
        self.assertEqual(ui['ui_mode'], 'standalone_evidence')
        self.assertFalse(ui['linked_job_flow'])
        self.assertFalse(ui['show_context_card'])
        self.assertTrue(ui['requires_gps'])
        self.assertTrue(ui['gps_banner']['required'])
        self.assertEqual(ui['primary_button']['label'], 'Submit Report')
