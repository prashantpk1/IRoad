"""
mobile_api/hard_pod/services/hard_pod_execute_integration.py

Execute Action bridge for Hard POD custody promotion.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.hard_pod.guards.hard_pod_replay_guard import HardPodReplayGuard
from mobile_api.hard_pod.models import HardPODCustodySubmission
from mobile_api.hard_pod.services.custody_authority_service import (
    HardPodCustodyAuthorityService,
)
from mobile_api.hard_pod.services.hard_pod_idempotency_service import (
    HardPodIdempotencyService,
)
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_hard_pod_action,
)


class HardPodExecuteIntegrationService:
    """Bind hard POD custody submissions to Execute Action promotion."""

    def __init__(
        self,
        *,
        idempotency: HardPodIdempotencyService | None = None,
        replay: HardPodReplayGuard | None = None,
        authority: HardPodCustodyAuthorityService | None = None,
    ) -> None:
        self._idempotency = idempotency or HardPodIdempotencyService()
        self._replay = replay or HardPodReplayGuard()
        self._authority = authority or HardPodCustodyAuthorityService()

    def validate_execute_requirements(self, context: Any) -> None:
        action = getattr(context, 'operation_action', None)
        if not is_hard_pod_action(action):
            return

        payload = dict(getattr(context, 'payload', None) or {})
        custody_submission_id = str(payload.get('custody_submission_id') or '').strip()
        client_submission_id = str(payload.get('client_submission_id') or '').strip()
        if custody_submission_id or client_submission_id:
            return

        raise ExecuteActionError(
            'Hard POD execute requires custody_submission_id or client_submission_id.',
            code='hard_pod_submission_required',
            http_status=400,
            message_key='mobile.hard_pod.submission_required',
            refresh_required=True,
        )

    def bind_action_log(self, context: Any, action_log: Any) -> HardPODCustodySubmission | None:
        action = getattr(context, 'operation_action', None)
        if not is_hard_pod_action(action):
            return None
        if context.idempotent_replay or action_log is None:
            return None

        tenant_schema = (getattr(context, 'tenant_schema', None) or '').strip()
        driver = getattr(context, 'driver', None)
        driver_id = str(getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or '').strip()
        shipment = getattr(context, 'shipment', None)
        shipment_id = str(
            getattr(shipment, 'pk', None)
            or getattr(shipment, 'shipment_id', None)
            or getattr(context, 'job_id', '')
            or ''
        ).strip()
        payload = dict(getattr(context, 'payload', None) or {})
        custody_submission_id = str(payload.get('custody_submission_id') or '').strip()
        client_submission_id = str(payload.get('client_submission_id') or '').strip()
        action_log_id = str(getattr(action_log, 'log_id', None) or getattr(action_log, 'pk', '') or '').strip()

        if not (tenant_schema and driver_id and shipment_id and action_log_id):
            return None

        submission = self._resolve_submission(
            tenant_schema=tenant_schema,
            driver_id=driver_id,
            shipment_id=shipment_id,
            custody_submission_id=custody_submission_id,
            client_submission_id=client_submission_id,
        )
        if submission is None:
            raise ExecuteActionError(
                'Hard POD custody submission not found.',
                code='hard_pod_submission_not_found',
                http_status=404,
                message_key='mobile.hard_pod.submission_not_found',
                refresh_required=True,
            )

        self._replay.assert_replay_scope(
            submission,
            shipment_id=shipment_id,
            driver_id=driver_id,
            tenant_schema=tenant_schema,
            integrity_checksum=(submission.integrity_checksum or '').strip(),
        )

        already_promoted = bool(getattr(submission, 'promoted_at', None)) or bool(
            (submission.promotion_action_log_id or '').strip()
        )
        if already_promoted and submission.promotion_action_log_id != action_log_id:
            raise ExecuteActionError(
                'Hard POD custody submission already promoted.',
                code='hard_pod_already_promoted',
                http_status=409,
                message_key='mobile.hard_pod.already_promoted',
                refresh_required=True,
            )

        if submission.promotion_action_log_id == action_log_id:
            self._attach_submission(context, submission, action_log_id)
            return submission

        with transaction.atomic():
            submission.promoted_at = submission.promoted_at or getattr(action_log, 'log_date', None)
            submission.promotion_action_log_id = action_log_id
            submission.save(update_fields=['promoted_at', 'promotion_action_log_id'])

        self._attach_submission(context, submission, action_log_id)
        return submission

    def build_execute_authority(self, context: Any, action_log: Any | None = None) -> dict[str, Any]:
        shipment = getattr(context, 'shipment', None)
        driver = getattr(context, 'driver', None)
        return self._authority.resolve_authority(
            tenant_schema=(getattr(context, 'tenant_schema', None) or '').strip(),
            shipment_id=str(
                getattr(shipment, 'pk', None)
                or getattr(shipment, 'shipment_id', None)
                or getattr(context, 'job_id', '')
                or ''
            ).strip(),
            driver_id=str(getattr(driver, 'pk', None) or getattr(driver, 'driver_id', '') or '').strip(),
            action_log_id=str(getattr(action_log, 'log_id', None) or getattr(action_log, 'pk', '') or '').strip(),
        )

    def _resolve_submission(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        shipment_id: str,
        custody_submission_id: str,
        client_submission_id: str,
    ) -> HardPODCustodySubmission | None:
        if custody_submission_id:
            return (
                HardPODCustodySubmission.objects.filter(
                    tenant_schema=tenant_schema,
                    driver_id=driver_id,
                    shipment_id=shipment_id,
                    pk=custody_submission_id,
                )
                .first()
            )

        if client_submission_id:
            existing = self._idempotency.get_by_client_submission(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                client_submission_id=client_submission_id,
            )
            if existing is not None and (existing.shipment_id or '').strip() == shipment_id:
                return existing

        return None

    def _attach_submission(self, context: Any, submission: HardPODCustodySubmission, action_log_id: str) -> None:
        context.resolver_meta = dict(getattr(context, 'resolver_meta', None) or {})
        context.resolver_meta['hard_pod_custody_submission'] = submission
        context.resolver_meta['hard_pod_custody_authority'] = self._authority.resolve_authority(
            tenant_schema=submission.tenant_schema,
            shipment_id=submission.shipment_id,
            driver_id=submission.driver_id,
            action_log_id=action_log_id,
        )
