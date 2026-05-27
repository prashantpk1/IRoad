"""
mobile_api/pod_capture/services/pod_capture_bundle_service.py

Bundle lifecycle orchestration: draft → ready (Execute consumes ready bundles).

POD Capture API uses this service only to **prepare** promotable bundles.
Action Log creation and promotion run in Execute Action via
:class:`~mobile_api.pod_capture.staging.evidence_promotion_service.EvidencePromotionService`.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.promotion_models import PodPromotionScope
from mobile_api.pod_capture.dto.staging_models import PODCaptureBundle, PODCaptureBundleStatus, StagingScope
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.policy.pod_evidence_immutability_policy import (
    assert_bundle_mutable_for_staging,
)
from mobile_api.pod_capture.services.media_integrity_service import MediaIntegrityService
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService


class PodCaptureBundleService:
    """Finalize and resolve staged bundles for downstream Execute Action promotion."""

    def __init__(
        self,
        *,
        staging: EvidenceStagingService | None = None,
        integrity: MediaIntegrityService | None = None,
    ) -> None:
        self._staging = staging or EvidenceStagingService()
        self._integrity = integrity or MediaIntegrityService()

    def finalize_bundle(self, context: PodCaptureContext) -> PODCaptureBundle:
        """Transition draft bundle → ``ready`` after media attach (capture phase only)."""
        bundle = context.bundle
        if bundle is None:
            raise PodCaptureError(
                'Bundle not initialized.',
                code='bundle_missing',
                http_status=500,
                message_key='mobile.pod_capture.bundle_missing',
            )

        if context.idempotent_replay:
            return bundle

        assert_bundle_mutable_for_staging(bundle)
        media = context.staged_media or self._staging.get_media(bundle.bundle_id)
        self._integrity.assign_media_checksums(media)
        digest = self._integrity.seal_bundle(bundle, media)
        bundle.integrity_checksum = digest
        self._staging.persist_bundle(bundle)
        bundle = self._staging.mark_ready(bundle)
        context.bundle = bundle
        return bundle

    def resolve_ready_bundle(
        self,
        bundle_id: str,
        *,
        scope: StagingScope | PodPromotionScope,
    ) -> PODCaptureBundle:
        """
        Load a bundle for Execute Action promotion (orphan-safe).

        Raises:
            PodCaptureError: Missing bundle, scope mismatch, or not ready.
        """
        staging_scope = _as_staging_scope(scope)
        token = (bundle_id or '').strip()
        try:
            import uuid as _uuid

            _uuid.UUID(token)
        except (TypeError, ValueError, AttributeError):
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_not_found')),
                code='bundle_not_found',
                http_status=404,
                message_key='mobile.pod_capture.bundle_not_found',
            )
        bundle = self._staging.get_bundle(token)
        if bundle is None:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_not_found')),
                code='bundle_not_found',
                http_status=404,
                message_key='mobile.pod_capture.bundle_not_found',
            )

        self._staging.assert_bundle_scope(bundle, staging_scope)

        if bundle.status == PODCaptureBundleStatus.PROMOTED:
            return bundle

        if bundle.status != PODCaptureBundleStatus.READY:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_not_ready')),
                code='bundle_not_ready',
                http_status=400,
                message_key='mobile.pod_capture.bundle_not_ready',
            )
        if bundle.is_expired():
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_expired')),
                code='bundle_expired',
                http_status=410,
                message_key='mobile.pod_capture.bundle_expired',
            )
        return bundle

    def build_execute_bundle_reference(self, bundle: PODCaptureBundle) -> dict[str, Any]:
        """Minimal bundle handle for Execute Action payloads (no workflow mutation)."""
        return {
            'bundle_id': bundle.bundle_id,
            'client_capture_id': bundle.client_capture_id,
            'shipment_id': bundle.shipment_id,
            'driver_id': bundle.driver_id,
            'tenant_schema': bundle.tenant_schema,
            'status': bundle.status.value,
            'media_count': bundle.media_count,
            'ready_for_execute': bundle.is_promotable(),
            'promoted': bundle.is_promoted(),
            'promotion_action_log_id': bundle.promotion_action_log_id,
        }

    def assert_orphan_bundle_prevented(
        self,
        bundle_id: str,
        *,
        scope: StagingScope | PodPromotionScope,
    ) -> PODCaptureBundle:
        """Execute hook — reject unknown bundle ids before Action Log side effects."""
        bundle = self.resolve_ready_bundle(bundle_id, scope=scope)
        media = self._staging.get_media(bundle.bundle_id)
        if not media:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_empty_media')),
                code='bundle_empty_media',
                http_status=400,
                message_key='mobile.pod_capture.bundle_empty_media',
            )
        return bundle


def _as_staging_scope(scope: StagingScope | PodPromotionScope) -> StagingScope:
    if isinstance(scope, StagingScope):
        return scope
    return scope.to_staging_scope()
