"""POD evidence consolidation for fragmented capture retries."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.execution.evidence.pod_evidence_consolidation import (
    consolidate_pod_evidence_dicts,
    consolidate_pod_evidence_items,
)


class PodEvidenceConsolidationTests(TestCase):
    def _requirements(self) -> dict:
        return {
            'signature': True,
            'video_max_count': 1,
            'photo_max_count': 10,
            'photo_min_count': 1,
        }

    def test_consolidates_many_retry_photos_to_cap(self):
        rows = [
            {'media_type': 'photo', 'file_ref': f'mobile/pod_evidence/p{i}.jpg'}
            for i in range(12)
        ]
        rows.append({'media_type': 'signature', 'file_ref': 'mobile/pod_evidence/sig.png'})
        rows.append({'media_type': 'video', 'file_ref': 'mobile/pod_evidence/v.mp4'})

        consolidated = consolidate_pod_evidence_dicts(rows, self._requirements())
        photo_count = sum(1 for row in consolidated if row['media_type'] == 'photo')
        self.assertEqual(photo_count, 10)
        self.assertEqual(len(consolidated), 12)

    def test_keeps_latest_video_and_signature(self):
        rows = [
            {'media_type': 'photo', 'file_ref': 'mobile/pod_evidence/p1.jpg'},
            {'media_type': 'signature', 'file_ref': 'mobile/pod_evidence/sig-old.png'},
            {'media_type': 'video', 'file_ref': 'mobile/pod_evidence/v-old.mp4'},
            {'media_type': 'signature', 'file_ref': 'mobile/pod_evidence/sig-new.png'},
            {'media_type': 'video', 'file_ref': 'mobile/pod_evidence/v-new.mp4'},
        ]
        consolidated = consolidate_pod_evidence_dicts(rows, self._requirements())
        refs = [row['file_ref'] for row in consolidated]
        self.assertIn('mobile/pod_evidence/sig-new.png', refs)
        self.assertIn('mobile/pod_evidence/v-new.mp4', refs)
        self.assertNotIn('mobile/pod_evidence/sig-old.png', refs)

    def test_namespace_items_consolidated(self):
        items = [
            SimpleNamespace(media_type='photo', file_ref=f'p{i}.jpg')
            for i in range(11)
        ]
        items.append(SimpleNamespace(media_type='video', file_ref='v.mp4'))
        consolidated = consolidate_pod_evidence_items(items, self._requirements())
        self.assertEqual(
            sum(1 for item in consolidated if item.media_type == 'photo'),
            10,
        )

    def test_optional_evidence_pod_capture_type_consolidates_videos(self):
        rows = [
            {'media_type': 'video', 'file_ref': 'mobile/pod_evidence/v1.mp4'},
            {'media_type': 'video', 'file_ref': 'mobile/pod_evidence/v2.mp4'},
            {'media_type': 'video', 'file_ref': 'mobile/pod_evidence/v3.mp4'},
        ]
        requirements = {
            'capture_mode': 'optional_evidence',
            'pod_capture_type': 'digital',
            'video_max_count': 1,
        }
        consolidated = consolidate_pod_evidence_dicts(rows, requirements)
        self.assertEqual(len(consolidated), 1)
        self.assertEqual(consolidated[0]['file_ref'], 'mobile/pod_evidence/v3.mp4')
