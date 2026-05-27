"""
mobile_api/hard_pod/services/custody_authority_service.py

Canonical custody authority reconciliation for Hard POD.
"""
from __future__ import annotations

from typing import Any

from mobile_api.hard_pod.models import HardPODCustodySubmission
from mobile_api.pod_capture.models import PODCaptureBundle


class HardPodCustodyAuthorityService:
    """Resolve a single canonical custody authority record."""

    def resolve_authority(
        self,
        *,
        tenant_schema: str,
        shipment_id: str,
        driver_id: str = '',
        action_log_id: str = '',
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        shipment = (shipment_id or '').strip()
        driver = (driver_id or '').strip()
        action_log = (action_log_id or '').strip()

        if not (schema and shipment):
            return self._empty()

        linked_submission = self._latest_submission(
            tenant_schema=schema,
            shipment_id=shipment,
            driver_id=driver,
            require_linked=True,
            action_log_id=action_log,
        )
        if linked_submission is not None:
            return {
                'custody_authority': 'execute_action_log',
                'authority_source': 'hard_pod_execute_link',
                'reconciled': True,
                'submission_id': str(linked_submission.pk),
                'client_submission_id': linked_submission.client_submission_id,
                'promotion_action_log_id': linked_submission.promotion_action_log_id,
                'capture_bundle_id': str(linked_submission.capture_bundle_id)
                if linked_submission.capture_bundle_id
                else None,
            }

        promoted_submission = self._latest_submission(
            tenant_schema=schema,
            shipment_id=shipment,
            driver_id=driver,
            require_linked=False,
        )
        if promoted_submission is not None and (
            bool(getattr(promoted_submission, 'promoted_at', None))
            or bool((promoted_submission.promotion_action_log_id or '').strip())
        ):
            return {
                'custody_authority': 'promoted_custody_submission',
                'authority_source': 'hard_pod_submission_promotion',
                'reconciled': bool(promoted_submission.promoted_at),
                'submission_id': str(promoted_submission.pk),
                'client_submission_id': promoted_submission.client_submission_id,
                'promotion_action_log_id': promoted_submission.promotion_action_log_id,
                'capture_bundle_id': str(promoted_submission.capture_bundle_id)
                if promoted_submission.capture_bundle_id
                else None,
            }

        legacy_bundle = (
            PODCaptureBundle.objects.filter(
                tenant_schema=schema,
                shipment_id=shipment,
                driver_id=driver or None,
            )
            .order_by('-created_at')
            .first()
        )
        if legacy_bundle is not None:
            return {
                'custody_authority': 'legacy_pod_capture',
                'authority_source': 'pod_capture_fallback',
                'reconciled': True,
                'submission_id': None,
                'client_submission_id': None,
                'promotion_action_log_id': legacy_bundle.promotion_action_log_id or None,
                'capture_bundle_id': str(legacy_bundle.id),
            }

        return self._empty()

    @staticmethod
    def _latest_submission(
        *,
        tenant_schema: str,
        shipment_id: str,
        driver_id: str,
        require_linked: bool,
        action_log_id: str = '',
    ) -> HardPODCustodySubmission | None:
        qs = HardPODCustodySubmission.objects.filter(
            tenant_schema=tenant_schema,
            shipment_id=shipment_id,
        )
        if driver_id:
            qs = qs.filter(driver_id=driver_id)
        if require_linked:
            qs = qs.exclude(promotion_action_log_id='')
            if action_log_id:
                qs = qs.filter(promotion_action_log_id=action_log_id)
        return qs.order_by('-promoted_at', '-submitted_at', '-created_at').first()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            'custody_authority': '',
            'authority_source': '',
            'reconciled': False,
            'submission_id': None,
            'client_submission_id': None,
            'promotion_action_log_id': None,
            'capture_bundle_id': None,
        }
