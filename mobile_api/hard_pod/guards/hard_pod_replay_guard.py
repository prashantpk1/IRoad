"""
mobile_api/hard_pod/guards/hard_pod_replay_guard.py

Replay-safe custody submit — same client_submission_id returns prior result.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from mobile_api.hard_pod.exceptions import HardPodError
from mobile_api.hard_pod.models import HardPODCustodySubmission


class HardPodReplayGuard:
    """Detect idempotent replay and reject cross-shipment reuse of submission keys."""

    def assert_replay_scope(
        self,
        existing: HardPODCustodySubmission,
        *,
        shipment_id: str,
        driver_id: str,
        tenant_schema: str,
        integrity_checksum: str | None = None,
    ) -> None:
        if (existing.tenant_schema or '').strip() != (tenant_schema or '').strip():
            raise HardPodError(
                str(_('mobile.hard_pod.submission_scope_mismatch')),
                code='tenant_scope_mismatch',
                http_status=403,
                message_key='mobile.hard_pod.submission_scope_mismatch',
            )
        if (existing.driver_id or '').strip() != (driver_id or '').strip():
            raise HardPodError(
                str(_('mobile.hard_pod.submission_scope_mismatch')),
                code='driver_scope_mismatch',
                http_status=403,
                message_key='mobile.hard_pod.submission_scope_mismatch',
            )
        if (existing.shipment_id or '').strip() != (shipment_id or '').strip():
            raise HardPodError(
                str(_('mobile.hard_pod.submission_shipment_mismatch')),
                code='submission_shipment_mismatch',
                http_status=409,
                message_key='mobile.hard_pod.submission_shipment_mismatch',
            )

        if integrity_checksum is not None:
            if str(existing.integrity_checksum or '').strip() != str(integrity_checksum or '').strip():
                raise HardPodError(
                    str(_('mobile.hard_pod.submission_integrity_mismatch')),
                    code='submission_integrity_mismatch',
                    http_status=409,
                    message_key='mobile.hard_pod.submission_integrity_mismatch',
                )

    def is_replay(self, existing: HardPODCustodySubmission | None) -> bool:
        return existing is not None
