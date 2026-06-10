"""Tests for staged bundle media type normalization on execute."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
)


class BundleMediaNormalizationTests(TestCase):
    def test_mislabeled_video_in_bundle_counts_as_video(self):
        row = SimpleNamespace(
            media_type='photo',
            file_ref='mobile/pod_evidence/149593.mp4',
            file_name='149593.mp4',
            mime_type='video/mp4',
            duration_seconds=5,
        )
        normalized = EvidenceValidationService._normalize_bundle_media_rows([row])
        self.assertEqual(normalized[0].media_type, 'video')
        self.assertEqual(
            EvidenceValidationService._resolve_row_media_type(row),
            'video',
        )
