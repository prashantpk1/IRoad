"""
mobile_api/pod_capture/staging/evidence_promotion_service.py

Promotion of staged POD evidence onto Action Log media rows (Execute Action phase).

Flow::

    POD Capture → bundle (ready) + staged media
    Execute Action → Action Log created (kernel)
    → EvidencePromotionService.promote_staged_bundle(...)
    → persist append-only media rows
    → mark bundle promoted (immutable)

This module MUST NOT call ``ActionExecutionService`` or shipment workflow side effects.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from mobile_api.execution.evidence.action_log_media_persistence import ActionLogMediaItem
from mobile_api.pod_capture.dto.promotion_models import (
    PodPromotionRequest,
    PodPromotionResult,
    PodPromotionScope,
)
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.guards.immutable_evidence_guard import ImmutableEvidenceGuard
from mobile_api.pod_capture.models import PODCapturePromotionAudit
from mobile_api.pod_capture.policy.pod_evidence_immutability_policy import (
    assert_bundle_mutable_for_staging,
    persist_pod_action_log_media,
)
from mobile_api.pod_capture.services.action_log_bundle_link import link_action_log_to_bundle
from mobile_api.pod_capture.services.media_integrity_service import MediaIntegrityService
from mobile_api.pod_capture.services.promotion_audit_service import PromotionAuditService
from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService

logger = logging.getLogger('mobile_api.pod_capture.promotion')


class EvidencePromotionService:
    """
    Bind a staged bundle to an Action Log after Execute creates the log row.

    Guarantees:

    * **Atomic** — media persist + bundle ``promoted`` in one DB transaction
    * **Replay-safe** — same ``action_log`` idempotently returns prior result
    * **Append-only** — ``replace_existing=False`` for POD media
    * **Shipment-bound** — tenant / driver / shipment scope enforced
    """

    def __init__(
        self,
        *,
        staging: EvidenceStagingService | None = None,
        bundle_service: Any | None = None,
        integrity: MediaIntegrityService | None = None,
        audit: PromotionAuditService | None = None,
    ) -> None:
        self._staging = staging or EvidenceStagingService()
        self._bundles = bundle_service
        self._integrity = integrity or MediaIntegrityService()
        self._audit = audit or PromotionAuditService()
        self._immutable = ImmutableEvidenceGuard()

    def promote_staged_bundle(
        self,
        request: PodPromotionRequest,
        *,
        promoted_by: str = '',
        execution_idempotency_key: str = '',
    ) -> PodPromotionResult:
        scope = request.scope
        bundle = self._bundle_service().assert_orphan_bundle_prevented(
            request.bundle_id,
            scope=scope,
        )
        action_log_id = _action_log_pk(request.action_log)

        replay = self._try_replay_promotion(bundle, action_log_id)
        if replay is not None:
            return replay

        self.assert_bundle_promotable(bundle)
        self._assert_promotion_scope(bundle, scope)

        media_rows = self._staging.get_media(bundle.bundle_id)
        if not media_rows:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_empty_media')),
                code='bundle_empty_media',
                http_status=400,
                message_key='mobile.pod_capture.bundle_empty_media',
            )

        self._integrity.verify_media_checksums(media_rows)
        self._integrity.verify_bundle_integrity(bundle, media_rows)

        items = staged_media_to_action_log_items(media_rows)
        self._immutable.assert_replace_allowed(
            replace_existing=False,
            immutable=True,
            action_log_id=action_log_id,
        )

        with transaction.atomic():
            created_ids = persist_pod_action_log_media(request.action_log, items)
            bundle = self._staging.mark_promoted(
                bundle,
                action_log_id=action_log_id,
            )
            link_action_log_to_bundle(request.action_log, bundle.bundle_id)
            self._audit.record_promotion(
                bundle,
                action_log_id=action_log_id,
                promoted_by=promoted_by,
                promotion_type=PODCapturePromotionAudit.PromotionType.INITIAL,
                execution_idempotency_key=execution_idempotency_key,
                replay_source=False,
            )

        logger.info(
            'pod_promotion bundle_id=%s action_log_id=%s media_rows=%s',
            bundle.bundle_id,
            action_log_id,
            len(created_ids),
        )
        return PodPromotionResult(
            bundle_id=bundle.bundle_id,
            action_log_id=action_log_id,
            media_row_ids=[str(pk) for pk in created_ids],
            replayed=False,
            promoted_at=bundle.promoted_at,
        )

    def promote_bundle_to_action_log(
        self,
        bundle: PODCaptureBundle,
        action_log: object,
        *,
        scope: PodPromotionScope | StagingScope,
        promoted_by: str = '',
        execution_idempotency_key: str = '',
    ) -> PodPromotionResult:
        promo_scope = scope if isinstance(scope, PodPromotionScope) else PodPromotionScope(
            tenant_schema=scope.tenant_schema,
            driver_id=scope.driver_id,
            shipment_id=scope.shipment_id,
        )
        return self.promote_staged_bundle(
            PodPromotionRequest(
                bundle_id=bundle.bundle_id,
                action_log=action_log,
                scope=promo_scope,
            ),
            promoted_by=promoted_by,
            execution_idempotency_key=execution_idempotency_key,
        )

    def assert_bundle_promotable(self, bundle: PODCaptureBundle) -> None:
        if bundle.status == PODCaptureBundleStatus.PROMOTED:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_already_promoted')),
                code='bundle_already_promoted',
                http_status=409,
                message_key='mobile.pod_capture.bundle_already_promoted',
            )
        if bundle.is_expired():
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_expired')),
                code='bundle_expired',
                http_status=410,
                message_key='mobile.pod_capture.bundle_expired',
            )
        if bundle.status == PODCaptureBundleStatus.REJECTED:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_rejected')),
                code='bundle_rejected',
                http_status=409,
                message_key='mobile.pod_capture.bundle_rejected',
            )
        if bundle.status != PODCaptureBundleStatus.READY:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_not_ready')),
                code='bundle_not_ready',
                http_status=400,
                message_key='mobile.pod_capture.bundle_not_ready',
            )

    def build_execute_media_payload(self, bundle_id: str) -> list[dict]:
        bundle = self._staging.get_bundle(bundle_id)
        if bundle is None:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_not_found')),
                code='bundle_not_found',
                http_status=404,
                message_key='mobile.pod_capture.bundle_not_found',
            )
        self.assert_bundle_promotable(bundle)
        rows = self._staging.get_media(bundle_id)
        return [
            {
                'media_type': row.media_type,
                'file_ref': row.file_ref,
                'file_name': row.file_name,
                'description': row.description,
                'captured_at': row.captured_at,
                'media_id': row.media_id,
                'sort_order': row.line_no,
            }
            for row in rows
        ]

    def _try_replay_promotion(
        self,
        bundle: PODCaptureBundle,
        action_log_id: str,
    ) -> PodPromotionResult | None:
        if not bundle.is_promoted():
            return None

        existing_log = (bundle.promotion_action_log_id or '').strip()
        if existing_log and existing_log == action_log_id:
            return PodPromotionResult(
                bundle_id=bundle.bundle_id,
                action_log_id=action_log_id,
                media_row_ids=[],
                replayed=True,
                promoted_at=bundle.promoted_at,
            )

        raise PodCaptureError(
            str(_('mobile.pod_capture.bundle_already_promoted')),
            code='bundle_already_promoted',
            http_status=409,
            message_key='mobile.pod_capture.bundle_already_promoted',
        )

    def _assert_promotion_scope(
        self,
        bundle: PODCaptureBundle,
        scope: PodPromotionScope,
    ) -> None:
        staging_scope = scope.to_staging_scope(client_capture_id=bundle.client_capture_id)
        self._staging.assert_bundle_scope(bundle, staging_scope)

    def _bundle_service(self) -> Any:
        if self._bundles is None:
            from mobile_api.pod_capture.services.pod_capture_bundle_service import (
                PodCaptureBundleService,
            )

            self._bundles = PodCaptureBundleService(staging=self._staging)
        return self._bundles


def staged_media_to_action_log_items(
    rows: list[PODCaptureMedia],
) -> list[ActionLogMediaItem]:
    items: list[ActionLogMediaItem] = []
    for row in rows:
        items.append(
            ActionLogMediaItem(
                media_type=row.media_type,
                description=row.description,
                captured_at=row.captured_at,
                media_id='',
                file_ref=row.file_ref,
                file_name=row.file_name,
                line_no=row.line_no,
                upload=None,
            )
        )
    return items


def _action_log_pk(action_log: Any) -> str:
    pk = getattr(action_log, 'pk', None)
    return str(pk or '').strip()
