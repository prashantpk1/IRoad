"""Tests for A7 POD evidence merge before execute validation."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from django.utils import timezone

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
)
from mobile_api.execution.services.a7_pod_evidence_resolver import (
    _merge_media_dicts,
    _pick_primary_bundle_id,
    _score_media_dicts,
    prepare_a7_execute_evidence,
)
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.staging.evidence_staging_service import (
    EvidenceStagingService,
    _InMemoryStagingStore,
)


class A7PodEvidenceResolverTests(TestCase):
    def test_merge_media_dedupes_by_file_ref(self):
        photo = {
            'media_type': 'photo',
            'file_ref': 'mobile/pod_evidence/p1.jpg',
            'line_no': 1,
        }
        video = {
            'media_type': 'photo',
            'file_ref': 'mobile/pod_evidence/v.mp4',
            'duration_seconds': 9,
            'line_no': 2,
        }
        merged = _merge_media_dicts([photo], [video])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1]['media_type'], 'video')

    def test_pick_primary_prefers_bundle_with_video(self):
        photo_bundle = {
            'bundle_id': 'bundle-photo',
            'score': _score_media_dicts(
                [{'media_type': 'photo', 'file_ref': 'mobile/pod_evidence/p1.jpg'}]
            ),
            'media': [{'media_type': 'photo', 'file_ref': 'mobile/pod_evidence/p1.jpg'}],
            'created_at': None,
        }
        video_bundle = {
            'bundle_id': 'bundle-video',
            'score': _score_media_dicts(
                [
                    {
                        'media_type': 'photo',
                        'file_ref': 'mobile/pod_evidence/v.mp4',
                        'duration_seconds': 9,
                    }
                ]
            ),
            'media': [
                {
                    'media_type': 'photo',
                    'file_ref': 'mobile/pod_evidence/v.mp4',
                    'duration_seconds': 9,
                }
            ],
            'created_at': None,
        }
        merged = _merge_media_dicts(
            photo_bundle['media'],
            video_bundle['media'],
        )
        primary = _pick_primary_bundle_id(
            [photo_bundle, video_bundle],
            merged,
        )
        self.assertEqual(primary, 'bundle-video')

    def test_is_a7_shipment_execute_by_action_code(self):
        from mobile_api.execution.services.a7_pod_evidence_resolver import (
            _is_a7_shipment_execute,
        )

        context = ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id='ship-1',
            action_code='A7',
        )
        self.assertTrue(_is_a7_shipment_execute(context))


class PrepareA7FragmentedBundleTests(TestCase):
    def setUp(self) -> None:
        self.store = _InMemoryStagingStore()
        self.staging = EvidenceStagingService(store=self.store)
        self.scope = StagingScope(
            tenant_schema='tenant_a',
            driver_id='drv-1',
            shipment_id='774aa680-add5-43ae-b485-77fa48c98c65',
            client_capture_id='cap-photo',
        )
        now = timezone.now()
        self.photo_bundle = PODCaptureBundle(
            bundle_id=str(uuid4()),
            client_capture_id='cap-photo',
            shipment_id=self.scope.shipment_id,
            driver_id=self.scope.driver_id,
            tenant_schema=self.scope.tenant_schema,
            status=PODCaptureBundleStatus.READY,
            content_hash='hash-photo',
            media_count=2,
            expires_at=now + timedelta(hours=24),
            created_at=now,
            updated_at=now,
        )
        self.video_bundle = PODCaptureBundle(
            bundle_id=str(uuid4()),
            client_capture_id='cap-video',
            shipment_id=self.scope.shipment_id,
            driver_id=self.scope.driver_id,
            tenant_schema=self.scope.tenant_schema,
            status=PODCaptureBundleStatus.READY,
            content_hash='hash-video',
            media_count=1,
            expires_at=now + timedelta(hours=24),
            created_at=now + timedelta(seconds=5),
            updated_at=now,
        )
        self.store.save_bundle(self.photo_bundle)
        self.store.save_bundle(self.video_bundle)
        prefix = self.scope.storage_prefix()
        self.store.save_media(
            self.photo_bundle.bundle_id,
            [
                PODCaptureMedia(
                    media_id='p1',
                    bundle_id=self.photo_bundle.bundle_id,
                    shipment_id=self.scope.shipment_id,
                    driver_id=self.scope.driver_id,
                    tenant_schema=self.scope.tenant_schema,
                    client_capture_id='cap-photo',
                    media_type='photo',
                    file_ref=f'{prefix}p1.jpg',
                ),
                PODCaptureMedia(
                    media_id='p2',
                    bundle_id=self.photo_bundle.bundle_id,
                    shipment_id=self.scope.shipment_id,
                    driver_id=self.scope.driver_id,
                    tenant_schema=self.scope.tenant_schema,
                    client_capture_id='cap-photo',
                    media_type='photo',
                    file_ref=f'{prefix}p2.jpg',
                ),
            ],
        )
        self.store.save_media(
            self.video_bundle.bundle_id,
            [
                PODCaptureMedia(
                    media_id='v1',
                    bundle_id=self.video_bundle.bundle_id,
                    shipment_id=self.scope.shipment_id,
                    driver_id=self.scope.driver_id,
                    tenant_schema=self.scope.tenant_schema,
                    client_capture_id='cap-video',
                    media_type='photo',
                    file_ref=f'{prefix}120802.mp4',
                    file_name='120802.mp4',
                ),
            ],
        )

    def _context(self, *, payload: dict | None = None) -> ExecuteActionContext:
        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1', driver_id='drv-1'),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=self.scope.shipment_id,
            action_code='A7',
            payload=payload
            or {
                'latitude': '22.29408',
                'longitude': '73.13741',
                'notes': 'Hg',
            },
        )
        ctx.shipment = SimpleNamespace(
            pk=self.scope.shipment_id,
            shipment_id=self.scope.shipment_id,
            shipment_no='SH-0022',
        )
        ctx.operation_action = SimpleNamespace(
            action_code='A7',
            auto_pod_post=True,
            hard_copy_collection=False,
            english_label='Upload POD',
            shipment_status_impact='',
            movement_status_impact='',
            booking_status_impact='',
        )
        return ctx

    @patch('mobile_api.pod_capture.models.PODCaptureBundle')
    @patch(
        'mobile_api.pod_capture.staging.evidence_staging_service.EvidenceStagingService',
    )
    def test_prepare_merges_photo_and_video_bundles(
        self,
        mock_staging_cls,
        mock_bundle_cls,
    ) -> None:
        mock_staging_cls.return_value = self.staging
        mock_bundle_cls.objects.filter.return_value.order_by.return_value.__getitem__.return_value = [
            self.video_bundle,
            self.photo_bundle,
        ]

        context = self._context(
            payload={
                'capture_bundle_id': self.photo_bundle.bundle_id,
                'latitude': '22.29408',
                'longitude': '73.13741',
                'notes': 'Hg',
            },
        )
        prepare_a7_execute_evidence(context)

        merged = list(
            (context.resolver_meta or {}).get('pod_capture_merged_bundle_media') or []
        )
        self.assertEqual(len(merged), 3)
        video_rows = [row for row in merged if row.get('media_type') == 'video']
        self.assertEqual(len(video_rows), 1)
        self.assertEqual(context.payload['capture_bundle_id'], self.video_bundle.bundle_id)

    @patch(
        'mobile_api.pod_capture.services.pod_capture_bundle_service.EvidenceStagingService',
    )
    @patch(
        'mobile_api.pod_capture.staging.evidence_staging_service.EvidenceStagingService',
    )
    @patch('mobile_api.pod_capture.models.PODCaptureBundle')
    def test_validate_passes_with_fragmented_staged_uploads(
        self,
        mock_bundle_cls,
        mock_staging_cls,
        mock_bundle_staging_cls,
    ) -> None:
        mock_staging_cls.return_value = self.staging
        mock_bundle_staging_cls.return_value = self.staging
        mock_bundle_cls.objects.filter.return_value.order_by.return_value.__getitem__.return_value = [
            self.video_bundle,
            self.photo_bundle,
        ]

        context = self._context()
        prepare_a7_execute_evidence(context)
        items = EvidenceValidationService._collect_evidence_media_items(context)
        video_count = sum(1 for item in items if item.media_type == 'video')
        self.assertGreaterEqual(video_count, 1)
        self.assertEqual(context.payload['capture_bundle_id'], self.video_bundle.bundle_id)
