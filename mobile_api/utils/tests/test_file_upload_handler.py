"""Tests for multipart media type inference."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.utils.file_upload_handler import infer_media_type


class InferMediaTypeTests(TestCase):
    def test_infers_video_from_content_type(self):
        self.assertEqual(
            infer_media_type(content_type='video/mp4'),
            'video',
        )

    def test_infers_video_from_mp4_path_when_explicit_missing(self):
        self.assertEqual(
            infer_media_type(
                explicit='',
                file_ref='mobile/pod_evidence/abc.mp4',
            ),
            'video',
        )

    def test_respects_explicit_photo(self):
        self.assertEqual(
            infer_media_type(
                explicit='photo',
                file_ref='mobile/pod_evidence/abc.mp4',
            ),
            'photo',
        )

    def test_infers_video_from_explicit_token(self):
        self.assertEqual(infer_media_type(explicit='Video'), 'video')
