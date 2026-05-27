"""
Security and ownership tests for POD evidence staging (durable ORM).
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

from django.test import TransactionTestCase
from django.utils import timezone

from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.guards.pod_capture_ownership_guard import PodCaptureOwnershipGuard
from mobile_api.pod_capture.guards.pod_capture_security_guard import PodCaptureSecurityGuard
from mobile_api.pod_capture.repositories.durable_bundle_repository import DurableBundleRepository
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


def _scope(
    *,
    tenant: str = 'tenant_a',
    driver: str = 'drv-1',
    shipment: str = 'ship-1',
    capture_id: str = 'cap-1',
) -> StagingScope:
    return StagingScope(
        tenant_schema=tenant,
        driver_id=driver,
        shipment_id=shipment,
        client_capture_id=capture_id,
    )


def _path(scope: StagingScope, filename: str) -> str:
    return f'{scope.storage_prefix()}{filename}'


def _bundle(
    scope: StagingScope,
    *,
    status: PODCaptureBundleStatus = PODCaptureBundleStatus.DRAFT,
    bundle_id: str | None = None,
    expires_at=None,
) -> PODCaptureBundle:
    now = timezone.now()
    return PODCaptureBundle(
        bundle_id=bundle_id or str(uuid.uuid4()),
        client_capture_id=scope.client_capture_id,
        shipment_id=scope.shipment_id,
        driver_id=scope.driver_id,
        tenant_schema=scope.tenant_schema,
        status=status,
        content_hash='hash-1',
        media_count=0,
        expires_at=expires_at or (now + timedelta(hours=24)),
        created_at=now,
        updated_at=now,
    )


def _media_row(scope: StagingScope, bundle_id: str, file_name: str = 'p.jpg') -> PODCaptureMedia:
    return PODCaptureMedia(
        media_id=str(uuid.uuid4()),
        bundle_id=bundle_id,
        shipment_id=scope.shipment_id,
        driver_id=scope.driver_id,
        tenant_schema=scope.tenant_schema,
        client_capture_id=scope.client_capture_id,
        media_type='photo',
        file_ref=_path(scope, file_name),
    )


class EvidenceStagingSecurityTests(TransactionTestCase):
    def setUp(self) -> None:
        self.repo = DurableBundleRepository()
        self.staging = EvidenceStagingService(repository=self.repo)

    def test_wrong_tenant_on_replay(self) -> None:
        scope_a = _scope(tenant='tenant_a')
        bundle = _bundle(scope_a)
        self.repo.save_bundle(bundle)

        scope_b = _scope(tenant='tenant_b')
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_bundle_scope(bundle, scope_b)
        self.assertEqual(exc.exception.code, 'tenant_scope_mismatch')

    def test_wrong_shipment_on_replay(self) -> None:
        scope = _scope(shipment='ship-1')
        bundle = _bundle(scope)
        other = _scope(shipment='ship-2')
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_bundle_scope(bundle, other)
        self.assertEqual(exc.exception.code, 'capture_id_shipment_mismatch')

    def test_wrong_driver_scope(self) -> None:
        scope = _scope(driver='drv-1')
        bundle = _bundle(scope)
        other = _scope(driver='drv-2')
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_bundle_scope(bundle, other)
        self.assertEqual(exc.exception.code, 'driver_scope_mismatch')

    def test_orphan_upload_path_rejected(self) -> None:
        scope = _scope()
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_file_ref_uploadable(
                'tenant-uploads/global/orphan.jpg',
                scope=scope,
            )
        self.assertEqual(exc.exception.code, 'orphan_upload')

    def test_cross_shipment_file_ref_rejected(self) -> None:
        scope_a = _scope(shipment='ship-1')
        scope_b = _scope(shipment='ship-2')
        bundle = _bundle(scope_a)
        row = _media_row(scope_a, bundle.bundle_id)
        self.repo.save_bundle(bundle)
        self.repo.save_media(bundle.bundle_id, [row])

        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_file_ref_uploadable(
                row.file_ref,
                scope=scope_b,
                bundle_id=str(uuid.uuid4()),
            )
        self.assertEqual(exc.exception.code, 'orphan_upload')

    def test_expired_bundle_rejected(self) -> None:
        scope = _scope()
        expired_at = timezone.now() - timedelta(hours=1)
        bundle = _bundle(scope, expires_at=expired_at)
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_bundle_mutable_for_capture(bundle)
        self.assertEqual(exc.exception.code, 'bundle_expired')
        self.assertEqual(bundle.status, PODCaptureBundleStatus.EXPIRED)

    def test_already_promoted_bundle_rejected(self) -> None:
        scope = _scope()
        bundle = _bundle(scope, status=PODCaptureBundleStatus.PROMOTED)
        bundle.promoted_at = timezone.now()
        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_bundle_mutable_for_capture(bundle)
        self.assertEqual(exc.exception.code, 'bundle_already_promoted')

    def test_promoted_file_ref_rejected(self) -> None:
        scope = _scope()
        bundle = _bundle(scope, status=PODCaptureBundleStatus.READY)
        row = _media_row(scope, bundle.bundle_id)
        self.repo.save_bundle(bundle)
        self.repo.save_media(bundle.bundle_id, [row])
        self.staging.mark_promoted(bundle, action_log_id='log-1')

        with self.assertRaises(PodCaptureError) as exc:
            self.staging.assert_file_ref_uploadable(row.file_ref, scope=scope)
        self.assertEqual(exc.exception.code, 'upload_already_promoted')

    def test_duplicate_bundle_idempotent_replay(self) -> None:
        driver = SimpleNamespace(
            pk='drv-1',
            driver_id='drv-1',
            driver_status='Active',
        )
        ctx = PodCaptureContext(
            driver=driver,
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload={},
            client_capture_id='cap-dup',
            content_hash='h1',
        )
        first = self.staging.stage_bundle(ctx)
        self.assertFalse(ctx.idempotent_replay)

        ctx2 = PodCaptureContext(
            driver=driver,
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload={},
            client_capture_id='cap-dup',
            content_hash='h1',
        )
        second = self.staging.stage_bundle(ctx2)
        self.assertTrue(ctx2.idempotent_replay)
        self.assertEqual(first.bundle_id, second.bundle_id)

    def test_bundle_lifecycle_draft_to_ready_to_promoted(self) -> None:
        scope = _scope()
        bundle = _bundle(scope)
        self.repo.save_bundle(bundle)
        ready = self.staging.mark_ready(bundle)
        self.assertEqual(ready.status, PODCaptureBundleStatus.READY)

        promoted = self.staging.mark_promoted(ready, action_log_id='log-99')
        self.assertEqual(promoted.status, PODCaptureBundleStatus.PROMOTED)
        self.assertEqual(promoted.promotion_action_log_id, 'log-99')


class PodCaptureSecurityGuardTests(TransactionTestCase):
    def test_path_includes_tenant_segment(self) -> None:
        prefix = PodCaptureSecurityGuard.build_expected_upload_prefix(
            tenant_schema='tenant_x',
            driver_pk='drv-9',
            shipment_pk='ship-9',
        )
        self.assertEqual(
            prefix,
            'mobile_driver_uploads/tenant_x/drv-9/ship-9/pod_capture/',
        )


class PodCaptureOwnershipGuardTests(TransactionTestCase):
    def test_forbidden_when_driver_does_not_own_shipment(self) -> None:
        guard = PodCaptureOwnershipGuard()
        driver = SimpleNamespace(pk='drv-other', driver_id='drv-other')
        shipment = SimpleNamespace(
            pk='ship-1',
            shipment_id='ship-1',
            driver_id='drv-1',
            booking_item_type='outbound',
            shipment_status='In Transit',
        )
        booking = SimpleNamespace(assigned_driver_id='drv-1')
        ctx = PodCaptureContext(
            driver=driver,
            tenant_schema='tenant_a',
            shipment_id='ship-1',
            payload={},
            shipment=shipment,
            booking=booking,
        )
        with self.assertRaises(PodCaptureError) as exc:
            guard.assert_shipment_driver_assignment(ctx, shipment=shipment, booking=booking)
        self.assertEqual(exc.exception.code, 'forbidden')

    def test_inactive_cancelled_shipment_rejected(self) -> None:
        guard = PodCaptureOwnershipGuard()
        shipment = SimpleNamespace(shipment_status='Cancelled')
        with self.assertRaises(PodCaptureError) as exc:
            guard.assert_shipment_active(shipment)
        self.assertEqual(exc.exception.code, 'job_inactive')
