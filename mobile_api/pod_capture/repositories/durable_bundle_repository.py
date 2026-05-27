"""
mobile_api/pod_capture/repositories/durable_bundle_repository.py

DB-backed, transaction-safe POD bundle persistence (HA / multi-worker safe).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from mobile_api.pod_capture.dto.staging_models import (
    PODCaptureBundle,
    PODCaptureBundleStatus,
    PODCaptureMedia,
)
from mobile_api.pod_capture.models import PODCaptureBundle as BundleORM
from mobile_api.pod_capture.models import PODCaptureMedia as MediaORM
from mobile_api.pod_capture.repositories.bundle_mappers import (
    bundle_dto_to_orm_defaults,
    bundle_orm_to_dto,
    media_dto_to_orm_defaults,
    media_orm_to_dto,
)


def normalize_file_ref(file_ref: str) -> str:
    return (file_ref or '').replace('\\', '/').lstrip('/')


@dataclass(frozen=True)
class FileRefRegistration:
    """Resolved file_ref ownership for orphan / promotion guards."""

    file_ref: str
    tenant_schema: str
    driver_id: str
    shipment_id: str
    client_capture_id: str
    bundle_id: str
    promoted: bool = False


class DurableBundleRepository:
    """All bundle/media staging operations — no process-local state."""

    def get_by_idempotency(
        self,
        *,
        tenant_schema: str,
        client_capture_id: str,
        driver_id: str,
    ) -> PODCaptureBundle | None:
        row = (
            BundleORM.objects.filter(
                tenant_schema=tenant_schema,
                client_capture_id=client_capture_id,
                driver_id=driver_id,
            )
            .first()
        )
        return bundle_orm_to_dto(row) if row else None

    def get_bundle(self, bundle_id: str) -> PODCaptureBundle | None:
        row = BundleORM.objects.filter(pk=bundle_id).first()
        return bundle_orm_to_dto(row) if row else None

    def get_bundle_for_update(self, bundle_id: str) -> BundleORM | None:
        return (
            BundleORM.objects.select_for_update()
            .filter(pk=bundle_id)
            .first()
        )

    def save_bundle(self, bundle: PODCaptureBundle) -> None:
        defaults = bundle_dto_to_orm_defaults(bundle)
        bundle_id = defaults.pop('id')
        created_at = defaults.pop('created_at', None)
        try:
            obj, created = BundleORM.objects.update_or_create(
                id=bundle_id,
                defaults=defaults,
            )
            if created and created_at is not None:
                BundleORM.objects.filter(pk=obj.pk).update(created_at=created_at)
        except IntegrityError:
            existing = self.get_by_idempotency(
                tenant_schema=bundle.tenant_schema,
                client_capture_id=bundle.client_capture_id,
                driver_id=bundle.driver_id,
            )
            if existing is not None:
                return
            raise

    def update_bundle(self, bundle: PODCaptureBundle) -> None:
        defaults = bundle_dto_to_orm_defaults(bundle)
        bundle_id = defaults.pop('id')
        defaults.pop('created_at', None)
        BundleORM.objects.filter(pk=bundle_id).update(**defaults)

    def get_media(self, bundle_id: str) -> list[PODCaptureMedia]:
        rows = MediaORM.objects.filter(bundle_id=bundle_id).order_by('line_no', 'uploaded_at')
        return [media_orm_to_dto(r) for r in rows]

    def save_media(self, bundle_id: str, rows: list[PODCaptureMedia]) -> None:
        with transaction.atomic():
            MediaORM.objects.filter(bundle_id=bundle_id).delete()
            for row in rows:
                defaults = media_dto_to_orm_defaults(row, bundle_pk=bundle_id)
                media_id = defaults.pop('id')
                defaults['file_ref_normalized'] = normalize_file_ref(row.file_ref)
                MediaORM.objects.create(id=media_id, **defaults)

    def get_file_ref_registration(self, file_ref: str) -> FileRefRegistration | None:
        normalized = normalize_file_ref(file_ref)
        if not normalized:
            return None
        row = (
            MediaORM.objects.filter(file_ref_normalized=normalized)
            .select_related('bundle')
            .order_by('-uploaded_at')
            .first()
        )
        if row is None:
            return None
        return FileRefRegistration(
            file_ref=normalized,
            tenant_schema=row.tenant_schema,
            driver_id=row.driver_id,
            shipment_id=row.shipment_id,
            client_capture_id=row.client_capture_id,
            bundle_id=str(row.bundle_id),
            promoted=row.promoted,
        )

    def mark_bundle_media_promoted(
        self,
        bundle_id: str,
        *,
        action_log_id: str,
    ) -> None:
        now = timezone.now()
        MediaORM.objects.filter(bundle_id=bundle_id).update(
            promoted=True,
            immutable=True,
            promoted_at=now,
            promoted_action_log_id=action_log_id,
        )

    def expire_stale_bundles(
        self,
        *,
        tenant_schema: str | None = None,
        now: Any | None = None,
    ) -> int:
        current = now or timezone.now()
        qs = BundleORM.objects.filter(
            bundle_status__in=[
                PODCaptureBundleStatus.DRAFT.value,
                PODCaptureBundleStatus.READY.value,
            ],
            expires_at__lt=current,
        )
        if tenant_schema:
            qs = qs.filter(tenant_schema=tenant_schema)
        return qs.update(bundle_status=PODCaptureBundleStatus.EXPIRED.value)
