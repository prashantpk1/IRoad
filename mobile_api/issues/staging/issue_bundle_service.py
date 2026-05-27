"""
mobile_api/issues/staging/issue_bundle_service.py

Durable persistence for operational issues, evidence, escalation, and timeline rows.
"""
from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from mobile_api.issues.models.operational_issue import (
    OperationalIssue,
    OperationalIssueEscalationEvent,
    OperationalIssueEvidence,
    OperationalIssueTimelineEntry,
)


def _normalize_file_ref(file_ref: str) -> str:
    return (file_ref or '').replace('\\', '/').lstrip('/')


class IssueBundleService:
    """Create issue header + immutable evidence in one transaction."""

    def create_issue_and_evidence(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        shipment_id: str,
        client_issue_id: str,
        issue_type: str,
        severity: str,
        notes: str,
        escalation_state: str,
        blocking_recommended: bool,
        latitude: str,
        longitude: str,
        integrity_checksum: str,
        evidence_items: list[dict[str, Any]],
    ) -> tuple[OperationalIssue, list[OperationalIssueEvidence]]:
        with transaction.atomic():
            issue = OperationalIssue.objects.create(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                shipment_id=shipment_id,
                client_issue_id=client_issue_id,
                issue_type=issue_type,
                severity=severity,
                notes=(notes or '').strip(),
                escalation_state=escalation_state,
                blocking_recommended=bool(blocking_recommended),
                latitude=(latitude or '').strip(),
                longitude=(longitude or '').strip(),
                integrity_checksum=integrity_checksum or '',
            )

            evidence_rows: list[OperationalIssueEvidence] = []
            for idx, item in enumerate(evidence_items, start=1):
                file_ref = (item.get('file_ref') or '').strip()
                if not file_ref:
                    continue
                evidence_rows.append(
                    OperationalIssueEvidence.objects.create(
                        issue=issue,
                        tenant_schema=tenant_schema,
                        shipment_id=shipment_id,
                        driver_id=driver_id,
                        media_type=(item.get('media_type') or '').strip(),
                        file_ref=file_ref,
                        file_ref_normalized=_normalize_file_ref(file_ref),
                        file_name=(item.get('file_name') or '').strip(),
                        mime_type=(item.get('mime_type') or '').strip(),
                        checksum=(item.get('checksum') or '').strip(),
                        line_no=int(item.get('sort_order') or item.get('line_no') or idx),
                        captured_at=item.get('captured_at'),
                        uploaded_at=timezone.now(),
                        immutable=True,
                    )
                )

            return issue, evidence_rows

    @staticmethod
    def try_get_by_client_issue(
        *,
        tenant_schema: str,
        driver_id: str,
        client_issue_id: str,
    ) -> OperationalIssue | None:
        return (
            OperationalIssue.objects.filter(
                tenant_schema=(tenant_schema or '').strip(),
                driver_id=(driver_id or '').strip(),
                client_issue_id=(client_issue_id or '').strip(),
            ).first()
        )

    @staticmethod
    def assert_replay_scope(
        *,
        existing: OperationalIssue,
        tenant_schema: str,
        driver_id: str,
        shipment_id: str,
        integrity_checksum: str | None = None,
    ) -> None:
        if (existing.tenant_schema or '').strip() != (tenant_schema or '').strip():
            raise ValueError('issue_replay_tenant_scope_mismatch')
        if (existing.driver_id or '').strip() != (driver_id or '').strip():
            raise ValueError('issue_replay_driver_scope_mismatch')
        if (existing.shipment_id or '').strip() != (shipment_id or '').strip():
            raise ValueError('issue_replay_shipment_scope_mismatch')
        if integrity_checksum is not None:
            if str(existing.integrity_checksum or '').strip() != str(integrity_checksum or '').strip():
                raise ValueError('issue_replay_integrity_mismatch')

    def create_race_safe(
        self,
        *,
        create_kwargs: dict[str, Any],
    ) -> tuple[OperationalIssue, list[OperationalIssueEvidence], bool]:
        """
        Attempt issue creation. On idempotency collision, reload existing.

        Returns (issue, evidence_rows, created).
        """
        try:
            issue, evidence = self.create_issue_and_evidence(**create_kwargs)
            return issue, evidence, True
        except IntegrityError:
            existing = self.try_get_by_client_issue(
                tenant_schema=create_kwargs['tenant_schema'],
                driver_id=create_kwargs['driver_id'],
                client_issue_id=create_kwargs['client_issue_id'],
            )
            if existing is None:
                raise
            self.assert_replay_scope(
                existing=existing,
                tenant_schema=create_kwargs['tenant_schema'],
                driver_id=create_kwargs['driver_id'],
                shipment_id=create_kwargs['shipment_id'],
                integrity_checksum=create_kwargs.get('integrity_checksum'),
            )
            evidence_rows = list(existing.evidence_rows.order_by('line_no'))
            return existing, evidence_rows, False
