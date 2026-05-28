"""
mobile_api/pod_capture/staging/evidence_staging_service.py

Secure shipment-scoped POD evidence staging (durable ORM-backed).

Prevents orphan, cross-tenant, cross-driver, and cross-shipment uploads via:

* bundle idempotency index ``(tenant_schema, client_capture_id, driver_id)``
* global ``file_ref`` registry with ownership scope and promotion flag
"""
from __future__ import annotations

from typing import Any
from types import SimpleNamespace

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
    StagingScope,
)
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.policy.pod_evidence_immutability_policy import (
    assert_bundle_mutable_for_staging,
)
from mobile_api.pod_capture.repositories.durable_bundle_repository import (
    DurableBundleRepository,
    normalize_file_ref,
)
from mobile_api.pod_capture.settings import pod_capture_default_expires_at
from mobile_api.pod_capture.settings import pod_capture_allow_orphan_retry


def _driver_pk(driver: Any) -> str:
    if driver is None:
        return ''
    pk = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
    return str(pk or '').strip()


class _InMemoryStagingStore:
    """
    Test-only compatibility store.

    Historically unit tests injected an in-memory store into EvidenceStagingService
    via `store=...`. The production code now defaults to `DurableBundleRepository`,
    but we keep this small adapter to avoid forcing DB-backed changes into
    SimpleTestCase suites.
    """

    def __init__(self) -> None:
        self._bundles: dict[str, PODCaptureBundle] = {}
        self._media: dict[str, list[PODCaptureMedia]] = {}
        # normalized_file_ref -> registration
        self._file_refs: dict[str, Any] = {}

    def get_by_idempotency(
        self,
        *,
        tenant_schema: str,
        client_capture_id: str,
        driver_id: str,
    ) -> PODCaptureBundle | None:
        for bundle in self._bundles.values():
            if (
                (bundle.tenant_schema or '').strip() == (tenant_schema or '').strip()
                and (bundle.client_capture_id or '').strip()
                == (client_capture_id or '').strip()
                and (bundle.driver_id or '').strip() == (driver_id or '').strip()
            ):
                return bundle
        return None

    def save_bundle(self, bundle: PODCaptureBundle) -> None:
        self._bundles[bundle.bundle_id] = bundle

    def update_bundle(self, bundle: PODCaptureBundle) -> None:
        self._bundles[bundle.bundle_id] = bundle

    def get_bundle(self, bundle_id: str) -> PODCaptureBundle | None:
        return self._bundles.get(bundle_id)

    def save_media(self, bundle_id: str, rows: list[PODCaptureMedia]) -> None:
        # In-memory tests treat media as replace/overwrite per bundle.
        self._media[bundle_id] = list(rows)

    def get_media(self, bundle_id: str) -> list[PODCaptureMedia]:
        return list(self._media.get(bundle_id) or [])

    def get_file_ref_registration(self, normalized_file_ref: str) -> Any | None:
        return self._file_refs.get(normalized_file_ref)

    def register_file_refs(
        self,
        rows: list[PODCaptureMedia],
        *,
        replace_bundle_id: str,
    ) -> None:
        for row in rows:
            normalized = normalize_file_ref(row.file_ref)
            if not normalized:
                continue
            self._file_refs[normalized] = SimpleNamespace(
                promoted=False,
                bundle_id=(replace_bundle_id or '').strip(),
                tenant_schema=(row.tenant_schema or '').strip(),
                driver_id=(row.driver_id or '').strip(),
                shipment_id=(row.shipment_id or '').strip(),
            )

    def mark_bundle_media_promoted(self, bundle_id: str, *, action_log_id: str) -> None:
        for reg in self._file_refs.values():
            if (getattr(reg, 'bundle_id', '') or '').strip() == (bundle_id or '').strip():
                reg.promoted = True


class EvidenceStagingService:
    """
    Create, validate, and transition staged POD capture bundles.

    State machine::

        draft → ready → promoted
                     ↘ expired | rejected
    """

    def __init__(
        self,
        *,
        repository: DurableBundleRepository | None = None,
        store: _InMemoryStagingStore | None = None,
    ) -> None:
        # `store=` is a test-only alias preserved for older unit tests.
        if store is not None and repository is not None:
            raise ValueError('Provide only one of `repository` or `store`.')
        self._repo = store or repository or DurableBundleRepository()

    @staticmethod
    def scope_from_context(context: PodCaptureContext) -> StagingScope:
        return StagingScope(
            tenant_schema=(context.tenant_schema or '').strip(),
            driver_id=_driver_pk(context.driver),
            shipment_id=(context.shipment_id or '').strip(),
            client_capture_id=(context.client_capture_id or '').strip(),
        )

    def stage_bundle(self, context: PodCaptureContext) -> PODCaptureBundle:
        scope = self.scope_from_context(context)
        existing = self._repo.get_by_idempotency(
            tenant_schema=scope.tenant_schema,
            client_capture_id=scope.client_capture_id,
            driver_id=scope.driver_id,
        )
        if existing is not None:
            self.assert_bundle_scope(existing, scope)
            self.assert_bundle_mutable_for_capture(existing)
            context.idempotent_replay = True
            context.bundle = existing
            context.staged_media = self._repo.get_media(existing.bundle_id)
            return existing

        now = timezone.now()
        bundle = PODCaptureBundle(
            bundle_id=PODCaptureBundle.new_id(),
            client_capture_id=scope.client_capture_id,
            shipment_id=scope.shipment_id,
            driver_id=scope.driver_id,
            tenant_schema=scope.tenant_schema,
            status=PODCaptureBundleStatus.DRAFT,
            content_hash=(context.content_hash or '').strip(),
            media_count=0,
            expires_at=pod_capture_default_expires_at(),
            promoted_at=None,
            created_at=now,
            updated_at=now,
            workflow_version=(context.workflow_version or '').strip(),
            pod_type=(getattr(context, 'pod_type', '') or '').strip(),
            notes=(getattr(context, 'notes', '') or '').strip(),
            latitude=(getattr(context, 'latitude', '') or '').strip(),
            longitude=(getattr(context, 'longitude', '') or '').strip(),
            capture_device_id=(getattr(context, 'capture_device_id', '') or '').strip(),
            capture_app_version=(getattr(context, 'capture_app_version', '') or '').strip(),
        )
        self._repo.save_bundle(bundle)
        context.bundle = bundle
        return bundle

    def attach_media(
        self,
        context: PodCaptureContext,
        rows: list[PODCaptureMedia],
    ) -> PODCaptureBundle:
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

        scope = self.scope_from_context(context)
        for row in rows:
            self.assert_media_scope(row, scope)

        self._assert_file_refs_available(rows, scope=scope, bundle_id=bundle.bundle_id)

        now = timezone.now()
        self._repo.save_media(bundle.bundle_id, rows)
        bundle.media_count = len(rows)
        bundle.updated_at = now
        self._repo.update_bundle(bundle)
        context.staged_media = rows
        context.bundle = bundle
        return bundle

    def mark_ready(self, bundle: PODCaptureBundle) -> PODCaptureBundle:
        self.assert_bundle_mutable_for_capture(bundle)
        if bundle.is_expired():
            return self.mark_expired(bundle)

        bundle.assert_transition(PODCaptureBundleStatus.READY)
        bundle.status = PODCaptureBundleStatus.READY
        bundle.updated_at = timezone.now()
        self._repo.update_bundle(bundle)
        return bundle

    def mark_promoted(
        self,
        bundle: PODCaptureBundle,
        *,
        action_log_id: str,
    ) -> PODCaptureBundle:
        if bundle.status == PODCaptureBundleStatus.PROMOTED:
            return bundle
        bundle.assert_transition(PODCaptureBundleStatus.PROMOTED)
        now = timezone.now()
        bundle.status = PODCaptureBundleStatus.PROMOTED
        bundle.promoted_at = now
        bundle.promotion_action_log_id = (action_log_id or '').strip() or None
        bundle.updated_at = now
        self._repo.update_bundle(bundle)
        self._repo.mark_bundle_media_promoted(
            bundle.bundle_id,
            action_log_id=(action_log_id or '').strip(),
        )
        return bundle

    def mark_expired(self, bundle: PODCaptureBundle) -> PODCaptureBundle:
        if bundle.status == PODCaptureBundleStatus.EXPIRED:
            return bundle
        if bundle.status not in {PODCaptureBundleStatus.DRAFT, PODCaptureBundleStatus.READY}:
            return bundle
        bundle.status = PODCaptureBundleStatus.EXPIRED
        bundle.updated_at = timezone.now()
        self._repo.update_bundle(bundle)
        return bundle

    def mark_rejected(self, bundle: PODCaptureBundle, *, reason: str = '') -> PODCaptureBundle:
        if bundle.status == PODCaptureBundleStatus.REJECTED:
            return bundle
        if bundle.is_promoted():
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_already_promoted')),
                code='bundle_already_promoted',
                http_status=409,
                message_key='mobile.pod_capture.bundle_already_promoted',
            )
        bundle.status = PODCaptureBundleStatus.REJECTED
        bundle.rejected_reason = (reason or '')[:255]
        bundle.updated_at = timezone.now()
        self._repo.update_bundle(bundle)
        return bundle

    def get_bundle(self, bundle_id: str) -> PODCaptureBundle | None:
        return self._repo.get_bundle(bundle_id)

    def get_media(self, bundle_id: str) -> list[PODCaptureMedia]:
        return self._repo.get_media(bundle_id)

    def persist_bundle(self, bundle: PODCaptureBundle) -> None:
        """Write bundle header fields to durable store."""
        self._repo.update_bundle(bundle)

    def assert_bundle_scope(self, bundle: PODCaptureBundle, scope: StagingScope) -> None:
        if (bundle.tenant_schema or '').strip() != scope.tenant_schema:
            raise PodCaptureError(
                str(_('mobile.pod_capture.tenant_scope_mismatch')),
                code='tenant_scope_mismatch',
                http_status=403,
                message_key='mobile.pod_capture.tenant_scope_mismatch',
            )
        if (bundle.driver_id or '').strip() != scope.driver_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.driver_scope_mismatch')),
                code='driver_scope_mismatch',
                http_status=403,
                message_key='mobile.pod_capture.driver_scope_mismatch',
            )
        if (bundle.shipment_id or '').strip() != scope.shipment_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.capture_id_shipment_mismatch')),
                code='capture_id_shipment_mismatch',
                http_status=409,
                message_key='mobile.pod_capture.capture_id_shipment_mismatch',
                refresh_required=True,
            )

    def assert_bundle_mutable_for_capture(self, bundle: PODCaptureBundle) -> None:
        if bundle.is_promoted() or bundle.status == PODCaptureBundleStatus.PROMOTED:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_already_promoted')),
                code='bundle_already_promoted',
                http_status=409,
                message_key='mobile.pod_capture.bundle_already_promoted',
            )
        assert_bundle_mutable_for_staging(bundle)
        if bundle.status == PODCaptureBundleStatus.REJECTED:
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_rejected')),
                code='bundle_rejected',
                http_status=409,
                message_key='mobile.pod_capture.bundle_rejected',
            )
        if bundle.is_expired():
            self.mark_expired(bundle)
            raise PodCaptureError(
                str(_('mobile.pod_capture.bundle_expired')),
                code='bundle_expired',
                http_status=410,
                message_key='mobile.pod_capture.bundle_expired',
            )

    def assert_media_scope(self, row: PODCaptureMedia, scope: StagingScope) -> None:
        if (row.tenant_schema or '').strip() != scope.tenant_schema:
            raise PodCaptureError(
                str(_('mobile.pod_capture.tenant_scope_mismatch')),
                code='tenant_scope_mismatch',
                http_status=403,
                message_key='mobile.pod_capture.tenant_scope_mismatch',
            )
        if (row.driver_id or '').strip() != scope.driver_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.driver_scope_mismatch')),
                code='driver_scope_mismatch',
                http_status=403,
                message_key='mobile.pod_capture.driver_scope_mismatch',
            )
        if (row.shipment_id or '').strip() != scope.shipment_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.shipment_scope_mismatch')),
                code='shipment_scope_mismatch',
                http_status=403,
                message_key='mobile.pod_capture.shipment_scope_mismatch',
            )
        if (row.client_capture_id or '').strip() != scope.client_capture_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.capture_scope_mismatch')),
                code='capture_scope_mismatch',
                http_status=409,
                message_key='mobile.pod_capture.capture_scope_mismatch',
            )

    def _assert_file_refs_available(
        self,
        rows: list[PODCaptureMedia],
        *,
        scope: StagingScope,
        bundle_id: str,
    ) -> None:
        for row in rows:
            normalized = normalize_file_ref(row.file_ref)
            if not normalized:
                continue

            existing = self._repo.get_file_ref_registration(normalized)
            if existing is None:
                continue

            if existing.promoted:
                raise PodCaptureError(
                    str(_('mobile.pod_capture.upload_already_promoted')),
                    code='upload_already_promoted',
                    http_status=409,
                    message_key='mobile.pod_capture.upload_already_promoted',
                )

            if existing.bundle_id != bundle_id:
                if (
                    existing.tenant_schema != scope.tenant_schema
                    or existing.driver_id != scope.driver_id
                    or existing.shipment_id != scope.shipment_id
                ):
                    if pod_capture_allow_orphan_retry():
                        continue
                    raise PodCaptureError(
                        str(_('mobile.pod_capture.orphan_upload')),
                        code='orphan_upload',
                        http_status=403,
                        message_key='mobile.pod_capture.orphan_upload',
                    )
                raise PodCaptureError(
                    str(_('mobile.pod_capture.upload_scope_conflict')),
                    code='upload_scope_conflict',
                    http_status=409,
                    message_key='mobile.pod_capture.upload_scope_conflict',
                )

    def assert_file_ref_uploadable(
        self,
        file_ref: str,
        *,
        scope: StagingScope,
        bundle_id: str | None = None,
    ) -> None:
        normalized = normalize_file_ref(file_ref)
        if not normalized:
            return

        expected_prefix = scope.storage_prefix()
        if not normalized.startswith(expected_prefix):
            if pod_capture_allow_orphan_retry():
                return
            raise PodCaptureError(
                str(_('mobile.pod_capture.orphan_upload')),
                code='orphan_upload',
                http_status=403,
                message_key='mobile.pod_capture.orphan_upload',
            )

        existing = self._repo.get_file_ref_registration(normalized)
        if existing is None:
            return

        if existing.promoted:
            raise PodCaptureError(
                str(_('mobile.pod_capture.upload_already_promoted')),
                code='upload_already_promoted',
                http_status=409,
                message_key='mobile.pod_capture.upload_already_promoted',
            )

        if bundle_id and existing.bundle_id == bundle_id:
            return

        if (
            existing.tenant_schema != scope.tenant_schema
            or existing.driver_id != scope.driver_id
            or existing.shipment_id != scope.shipment_id
        ):
            if pod_capture_allow_orphan_retry():
                return
            raise PodCaptureError(
                str(_('mobile.pod_capture.orphan_upload')),
                code='orphan_upload',
                http_status=403,
                message_key='mobile.pod_capture.orphan_upload',
            )

        if bundle_id and existing.bundle_id != bundle_id:
            raise PodCaptureError(
                str(_('mobile.pod_capture.upload_scope_conflict')),
                code='upload_scope_conflict',
                http_status=409,
                message_key='mobile.pod_capture.upload_scope_conflict',
            )
