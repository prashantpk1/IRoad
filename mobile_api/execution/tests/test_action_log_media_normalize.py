"""Tests for action-log media normalization."""
from __future__ import annotations

from unittest import TestCase

from mobile_api.execution.evidence.action_log_media_persistence import (
    normalize_media_items,
)


class NormalizeMediaItemsTests(TestCase):
    def test_infers_video_from_mp4_file_ref(self):
        items = normalize_media_items(
            [
                {
                    'file_ref': 'mobile/pod_evidence/clip.mp4',
                }
            ]
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].media_type, 'video')

    def test_photo_label_corrected_when_duration_seconds_set(self):
        items = normalize_media_items(
            [
                {
                    'media_type': 'photo',
                    'file_ref': 'mobile/pod_evidence/149593.mp4',
                    'duration_seconds': 5,
                }
            ]
        )
        self.assertEqual(items[0].media_type, 'video')
