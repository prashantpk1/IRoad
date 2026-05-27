"""
mobile_api/pod_capture/services/pod_capture_orchestrator.py

POD evidence capture orchestrator — shipment jobs only; no workflow mutation.

Pipeline::

    schema_context(tenant)
      → assert shipment-only + ownership
      → load sync metadata (read-only Job Detail fingerprints)
      → stale guard
      → validation + media security
      → stage bundle (idempotent client_capture_id)
      → attach media
      → validate + mark READY
      → build response

Future: Execute Action calls :class:`EvidencePromotionService` — not this module.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

from django_tenants.utils import schema_context

from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.pod_capture_response_builder import PodCaptureResponseBuilder
from mobile_api.pod_capture.guards.pod_capture_ownership_guard import PodCaptureOwnershipGuard
from mobile_api.pod_capture.guards.pod_capture_security_guard import PodCaptureSecurityGuard
from mobile_api.pod_capture.guards.pod_capture_stale_guard import PodCaptureStaleGuard
from mobile_api.pod_capture.services.pod_capture_bundle_service import PodCaptureBundleService
from mobile_api.pod_capture.services.pod_capture_media_service import PodCaptureMediaService
from mobile_api.pod_capture.services.pod_capture_validation_service import (
    PodCaptureValidationService,
)
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService

logger = logging.getLogger('mobile_api.pod_capture')


class PodCaptureOrchestrator:
    """
    Stage POD evidence for one shipment.

    Does **not** call ``ActionExecutionService``, kernel side effects, or shipment saves.
    """

    def __init__(
        self,
        *,
        ownership_guard: PodCaptureOwnershipGuard | None = None,
        stale_guard: PodCaptureStaleGuard | None = None,
        validation_service: PodCaptureValidationService | None = None,
        media_service: PodCaptureMediaService | None = None,
        staging_service: EvidenceStagingService | None = None,
        bundle_service: PodCaptureBundleService | None = None,
        response_builder: PodCaptureResponseBuilder | None = None,
    ) -> None:
        self._staging = staging_service or EvidenceStagingService()
        self._ownership = ownership_guard or PodCaptureOwnershipGuard(staging=self._staging)
        self._stale = stale_guard or PodCaptureStaleGuard()
        self._validation = validation_service or PodCaptureValidationService()
        self._media = media_service or PodCaptureMediaService(staging=self._staging)
        self._bundle = bundle_service or PodCaptureBundleService(staging=self._staging)
        self._response = response_builder or PodCaptureResponseBuilder()

    def capture_pod_evidence(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        shipment_id: str,
        payload: Mapping[str, Any],
        request: Any | None = None,
        user_id: str = '',
        job_type: str = 'shipment',
    ) -> dict[str, Any]:
        """
        Stage one POD evidence bundle and return API ``data`` payload.

        Args:
            driver: Authenticated driver master row.
            tenant_schema: JWT tenant schema name.
            shipment_id: Shipment UUID or shipment_no.
            payload: Validated serializer dict.
            job_type: Must be ``shipment`` (enforced).
        """
        schema = (tenant_schema or '').strip()
        context = PodCaptureContext(
            driver=driver,
            tenant_schema=schema,
            shipment_id=(shipment_id or '').strip(),
            payload=payload,
            request=request,
            user_id=user_id,
        )

        with schema_context(schema):
            return self._capture_in_schema(context, job_type=job_type)

    def _capture_in_schema(
        self,
        context: PodCaptureContext,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        self._ownership.assert_shipment_only(job_type=job_type)
        self._ownership.resolve_shipment(context)
        self._media.populate_context_from_payload(context)
        self._ownership.validate_capture_scope(context)
        self._hydrate_sync_metadata(context)

        self._staging.stage_bundle(context)
        if context.idempotent_replay and context.bundle is not None:
            self._ownership.assert_bundle_allowed_for_capture(context, context.bundle)
            logger.info(
                'pod_capture replay client_capture_id=%s bundle_id=%s',
                context.client_capture_id,
                getattr(context.bundle, 'bundle_id', ''),
            )
            return self._response.build(context)

        self._stale.assert_not_stale(context)
        self._validation.validate_capture_request(context)
        secured_items = self._media.secure_media_for_capture(context)

        staged_rows = self._media.build_staged_media_rows(context, secured_items)
        self._staging.attach_media(context, staged_rows)
        self._bundle.finalize_bundle(context)
        self._record_hard_pod_custody_if_needed(context)

        logger.info(
            'pod_capture staged bundle_id=%s shipment_id=%s media_count=%s',
            context.bundle.bundle_id if context.bundle else '',
            context.shipment_id,
            len(context.staged_media),
        )
        return self._response.build(context)

    def _record_hard_pod_custody_if_needed(self, context: PodCaptureContext) -> None:
        """Append-only Hard POD custody when capture payload indicates physical POD."""
        bundle = context.bundle
        if bundle is None or context.idempotent_replay:
            return
        payload = context.payload or {}
        pod_type = str(payload.get('pod_type') or '').strip().casefold()
        hard_flag = bool(payload.get('hard_pod') or payload.get('hard_copy'))
        if pod_type not in {'hard', 'hard_pod', 'hardcopy'} and not hard_flag:
            return
        from mobile_api.pod_capture.services.hard_pod_custody_service import HardPODCustodyService

        HardPODCustodyService().record_collection(
            bundle,
            document_serial=str(payload.get('document_serial') or '').strip(),
            document_reference=str(payload.get('document_reference') or '').strip(),
            receiver_name=str(payload.get('receiver_name') or '').strip(),
            receiver_identity_ref=str(payload.get('receiver_identity') or '').strip(),
            actor_id=str(getattr(context.driver, 'pk', '') or ''),
            actor_label=str(getattr(context.driver, 'driver_no', '') or ''),
        )

    def _hydrate_sync_metadata(self, context: PodCaptureContext) -> None:
        """
        Read-only sync fingerprints from Job Detail (no workflow mutation).

        Foundation: lightweight hash from shipment updated_at when full projection
        cache is not wired — Execute stale guard remains authoritative for actions.
        """
        shipment = context.shipment
        if shipment is None:
            context.sync_metadata = {}
            return

        updated = getattr(shipment, 'updated_at', None)
        shipment_version = updated.isoformat() if hasattr(updated, 'isoformat') else ''
        context.sync_metadata = {
            'content_hash': shipment_version,
            'workflow_version': shipment_version,
            'entity_versions': {
                'shipment': shipment_version,
            },
        }
