"""
mobile_api/pod_capture/services/promotion_audit_service.py

Legal-grade promotion audit rows (bundle ↔ Action Log forensic chain).
"""
from __future__ import annotations

from django.utils import timezone

from mobile_api.pod_capture.dto.staging_models import PODCaptureBundle
from mobile_api.pod_capture.models import PODCapturePromotionAudit


class PromotionAuditService:
    """Persist append-only promotion audit records."""

    def record_promotion(
        self,
        bundle: PODCaptureBundle,
        *,
        action_log_id: str,
        promoted_by: str = '',
        promotion_type: str = PODCapturePromotionAudit.PromotionType.INITIAL,
        execution_idempotency_key: str = '',
        replay_source: bool = False,
    ) -> PODCapturePromotionAudit:
        return PODCapturePromotionAudit.objects.create(
            bundle_id=bundle.bundle_id,
            action_log_id=action_log_id,
            shipment_id=bundle.shipment_id,
            driver_id=bundle.driver_id,
            tenant_schema=bundle.tenant_schema,
            promoted_at=bundle.promoted_at or timezone.now(),
            promoted_by=(promoted_by or '').strip(),
            promotion_type=promotion_type,
            execution_idempotency_key=(execution_idempotency_key or '').strip(),
            replay_source=replay_source,
            bundle_integrity_checksum=getattr(bundle, 'integrity_checksum', '') or '',
            capture_device_id=getattr(bundle, 'capture_device_id', '') or '',
            capture_app_version=getattr(bundle, 'capture_app_version', '') or '',
        )
