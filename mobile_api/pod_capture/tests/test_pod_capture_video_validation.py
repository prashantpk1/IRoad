"""Video duration validation for POD capture."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput
from mobile_api.pod_capture.services.pod_capture_validation_service import (
    PodCaptureValidationService,
)


class PodCaptureVideoValidationTests(SimpleTestCase):
    def test_rejects_video_longer_than_15_seconds(self):
        items = [
            PODCaptureMediaItemInput(
                media_type='video',
                file_ref='mobile/pod_evidence/clip.mp4',
                duration_seconds=16.0,
            )
        ]
        with self.assertRaises(Exception) as exc:
            PodCaptureValidationService._validate_video_duration(
                items,
                {'video_max_duration_seconds': 15},
            )
        self.assertEqual(exc.exception.code, 'video_duration_exceeded')

    def test_allows_video_within_limit(self):
        items = [
            PODCaptureMediaItemInput(
                media_type='video',
                file_ref='mobile/pod_evidence/clip.mp4',
                duration_seconds=8.0,
            )
        ]
        PodCaptureValidationService._validate_video_duration(
            items,
            {'video_max_duration_seconds': 15},
        )
