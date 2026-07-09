"""Tests for evidence requirement flag sync."""
from __future__ import annotations

from django.test import SimpleTestCase

from mobile_api.helpers.evidence_requirement_flags import (
    normalize_evidence_requirements,
    sync_row_evidence_flags,
)


class EvidenceRequirementFlagTests(SimpleTestCase):
    def test_optional_photo_video_shows_slots_without_requires_flags(self):
        row = sync_row_evidence_flags(
            {
                'execution_requirements': {
                    'photo_enabled': True,
                    'video_enabled': True,
                    'photo_min_count': 0,
                    'video_min_count': 0,
                },
            },
        )
        req = row['execution_requirements']
        self.assertTrue(row['show_photo'])
        self.assertTrue(row['show_video'])
        self.assertFalse(row['requires_photo'])
        self.assertFalse(row['requires_video'])
        self.assertFalse(req['photo'])
        self.assertFalse(req['video'])
        self.assertTrue(req['allow_submit_without_media'])

    def test_driver_evidence_photo_and_video_always_optional(self):
        row = sync_row_evidence_flags(
            {
                'execution_requirements': {
                    'photo_enabled': True,
                    'photo_min_count': 2,
                    'video_min_count': 1,
                },
            },
        )
        req = row['execution_requirements']
        self.assertFalse(row['requires_photo'])
        self.assertFalse(row['requires_video'])
        self.assertFalse(req['photo'])
        self.assertFalse(req['video'])
        self.assertEqual(req['photo_min_count'], 0)
        self.assertEqual(req['video_min_count'], 0)
        self.assertTrue(req['photo_optional'])
        self.assertTrue(req['video_optional'])
        self.assertTrue(req['allow_submit_without_media'])

    def test_tenant_media_min_counts_overridden_to_optional(self):
        req = normalize_evidence_requirements(
            {
                'video_min_count': 2,
                'video': True,
                'photo_min_count': 3,
                'photo': True,
            },
        )
        self.assertEqual(req['photo_min_count'], 0)
        self.assertEqual(req['video_min_count'], 0)
        self.assertFalse(req['photo'])
        self.assertFalse(req['video'])
        self.assertTrue(req['photo_optional'])
        self.assertTrue(req['video_optional'])

    def test_note_section_always_visible_for_optional_evidence(self):
        row = sync_row_evidence_flags(
            {
                'execution_requirements': {
                    'requires_evidence_capture': True,
                    'capture_mode': 'optional_evidence',
                },
            },
        )
        self.assertTrue(row['show_note'])

    def test_legacy_photo_true_means_show_not_enforce(self):
        req = normalize_evidence_requirements(
            {
                'photo': True,
                'video': True,
                'photo_min_count': 0,
                'video_min_count': 0,
            },
        )
        self.assertTrue(req['photo_enabled'])
        self.assertTrue(req['video_enabled'])
        self.assertFalse(req['photo'])
        self.assertFalse(req['video'])
        self.assertTrue(req['photo_optional'])
        self.assertTrue(req['video_optional'])
