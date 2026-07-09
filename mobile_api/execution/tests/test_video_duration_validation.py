"""Video clip max duration (60s) on POD capture and A7 execute."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
)
from mobile_api.execution.evidence.video_duration_validation import (
    video_duration_exceeded_message,
)
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.pod_capture.dto.staging_models import PODCaptureMediaItemInput
from mobile_api.pod_capture.services.pod_capture_validation_service import (
    PodCaptureValidationService,
)


class VideoDurationValidationTests(TestCase):
    def test_message_text(self):
        self.assertIn('60', video_duration_exceeded_message())
        self.assertIn('seconds', video_duration_exceeded_message().casefold())

    def test_pod_capture_rejects_long_clip(self):
        items = [
            PODCaptureMediaItemInput(
                media_type='video',
                file_ref='mobile/pod_evidence/clip.mp4',
                duration_seconds=60.1,
            )
        ]
        with self.assertRaises(Exception) as exc:
            PodCaptureValidationService._validate_video_duration(
                items,
                {'video_max_duration_seconds': 60},
            )
        self.assertEqual(exc.exception.code, 'video_duration_exceeded')
        self.assertIn('60', str(exc.exception))

    def test_pod_capture_allows_sixty_seconds_exactly(self):
        items = [
            PODCaptureMediaItemInput(
                media_type='video',
                file_ref='mobile/pod_evidence/clip.mp4',
                duration_seconds=60.0,
            )
        ]
        PodCaptureValidationService._validate_video_duration(
            items,
            {'video_max_duration_seconds': 60},
        )

    def test_execute_a7_rejects_long_clip(self):
        context = ExecuteActionContext(
            driver=None,
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id='ship-1',
            action_code='A7',
            payload={'media': []},
        )
        service = EvidenceValidationService()
        items = [
            SimpleNamespace(
                media_type='video',
                file_ref='mobile/pod_evidence/clip.mp4',
                upload=None,
                media_id='',
                duration_seconds=61.0,
            )
        ]
        requirements = {'video': True, 'video_min_count': 1, 'video_max_duration_seconds': 60}
        with self.assertRaises(ExecuteActionError) as exc:
            service._validate_video_duration(items, requirements)
        self.assertEqual(exc.exception.code, 'video_duration_exceeded')
