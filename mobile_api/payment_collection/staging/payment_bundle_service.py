"""
mobile_api/payment_collection/staging/payment_bundle_service.py

Durable persistence helpers for payment collection staging.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from mobile_api.payment_collection.models import (
    PaymentCollectionBundle,
    PaymentCollectionEvidence,
    PaymentCollectionAudit,
)


def _normalize_file_ref(file_ref: str) -> str:
    return (file_ref or '').replace('\\', '/').lstrip('/')


class PaymentBundleService:
    """Create payment bundles + immutable evidence rows + audit row."""

    def create_bundle_and_evidence(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        shipment_id: str,
        client_payment_id: str,
        amount: Decimal,
        expected_amount: Decimal,
        variance_detected: bool,
        payment_mode: str,
        notes: str,
        integrity_checksum: str,
        evidence_items: list[dict[str, Any]],
        audit_execution_idempotency_key: str = '',
        replay_source: bool = False,
    ) -> tuple[PaymentCollectionBundle, list[PaymentCollectionEvidence], PaymentCollectionAudit]:
        with transaction.atomic():
            bundle = PaymentCollectionBundle.objects.create(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                shipment_id=shipment_id,
                client_payment_id=client_payment_id,
                amount=amount,
                expected_amount=expected_amount,
                variance_detected=variance_detected,
                payment_mode=(payment_mode or '').strip(),
                notes=(notes or '').strip(),
                integrity_checksum=integrity_checksum or '',
            )

            evidence_rows: list[PaymentCollectionEvidence] = []
            for idx, item in enumerate(evidence_items, start=1):
                file_ref = (item.get('file_ref') or '').strip()
                if not file_ref:
                    continue
                evidence_rows.append(
                    PaymentCollectionEvidence.objects.create(
                        bundle=bundle,
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

            audit = PaymentCollectionAudit.objects.create(
                bundle=bundle,
                tenant_schema=tenant_schema,
                shipment_id=shipment_id,
                driver_id=driver_id,
                action_log_id='',
                execution_idempotency_key=audit_execution_idempotency_key or '',
                replay_source=bool(replay_source),
            )

            return bundle, evidence_rows, audit

