"""
mobile_api/hard_pod/services/hard_pod_idempotency_service.py

DB-backed idempotency for Hard POD custody submissions.
"""
from __future__ import annotations

from typing import Any

from django.db import IntegrityError

from mobile_api.hard_pod.models import HardPODCustodySubmission


class HardPodIdempotencyService:
    """Lookup and create submission rows with replay-safe unique constraint."""

    def get_by_client_submission(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        client_submission_id: str,
    ) -> HardPODCustodySubmission | None:
        return (
            HardPODCustodySubmission.objects.filter(
                tenant_schema=(tenant_schema or '').strip(),
                driver_id=(driver_id or '').strip(),
                client_submission_id=(client_submission_id or '').strip(),
            )
            .first()
        )

    def create_submission(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        shipment_id: str,
        client_submission_id: str,
        integrity_checksum: str = '',
        receiver_name: str = '',
        receiver_contact: str = '',
        handoff_notes: str = '',
        latitude: str = '',
        longitude: str = '',
        capture_bundle_id: str | None = None,
    ) -> tuple[HardPODCustodySubmission, bool]:
        """
        Create submission row.

        Returns ``(submission, created)``. On unique race, reloads existing row.
        """
        bundle_uuid = None
        if capture_bundle_id:
            try:
                import uuid as _uuid

                bundle_uuid = _uuid.UUID(str(capture_bundle_id).strip())
            except (TypeError, ValueError, AttributeError):
                bundle_uuid = None

        try:
            row = HardPODCustodySubmission.objects.create(
                tenant_schema=(tenant_schema or '').strip(),
                driver_id=(driver_id or '').strip(),
                shipment_id=(shipment_id or '').strip(),
                client_submission_id=(client_submission_id or '').strip(),
                receiver_name=(receiver_name or '').strip(),
                receiver_contact=(receiver_contact or '').strip(),
                handoff_notes=(handoff_notes or '').strip(),
                latitude=(latitude or '').strip(),
                longitude=(longitude or '').strip(),
                capture_bundle_id=bundle_uuid,
                integrity_checksum=(integrity_checksum or '').strip(),
            )
            return row, True
        except IntegrityError:
            existing = self.get_by_client_submission(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                client_submission_id=client_submission_id,
            )
            if existing is None:
                raise
            return existing, False
