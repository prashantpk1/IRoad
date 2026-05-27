"""
mobile_api/payment_collection/services/payment_collection_service.py

Orchestrate payment collection evidence staging (prep-only).
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Mapping

from mobile_api.payment_collection.dto.payment_response_builder import (
    PaymentResponseBuilder,
)
from mobile_api.payment_collection.exceptions import PaymentCollectionError

from mobile_api.payment_collection.services.payment_idempotency_service import (
    PaymentIdempotencyService,
)
from mobile_api.payment_collection.services.payment_reconciliation_service import (
    PaymentReconciliationService,
)
from mobile_api.payment_collection.services.payment_validation_service import (
    PaymentValidationService,
)
from mobile_api.payment_collection.staging.payment_bundle_service import (
    PaymentBundleService,
)


def _driver_pk(driver: Any) -> str:
    pk = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
    return str(pk or '').strip()


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class PaymentCollectionService:
    """Prep-only staging for driver COD payment collection evidence."""

    def __init__(
        self,
        *,
        validation: PaymentValidationService | None = None,
        idempotency: PaymentIdempotencyService | None = None,
        reconciliation: PaymentReconciliationService | None = None,
        bundle_service: PaymentBundleService | None = None,
        response_builder: PaymentResponseBuilder | None = None,
    ) -> None:
        self._validation = validation or PaymentValidationService()
        self._idempotency = idempotency or PaymentIdempotencyService()
        self._reconciliation = reconciliation or PaymentReconciliationService()
        self._bundle_service = bundle_service or PaymentBundleService()
        self._response_builder = response_builder or PaymentResponseBuilder()

    def stage_payment(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        client_payment_id = (payload.get('client_payment_id') or '').strip()
        shipment_ref = (payload.get('shipment_id') or '').strip()
        driver_id = _driver_pk(driver)

        amount = Decimal(str(payload.get('amount') or 0))
        notes = str(payload.get('notes') or '').strip()
        payment_mode = str(payload.get('payment_mode') or '').strip()
        proof_media = list(payload.get('proof_media') or [])
        proof_refs = [
            str(m.get('file_ref') or '').replace('\\', '/').lstrip('/')
            for m in proof_media
        ]

        # Idempotency must short-circuit writes early.
        existing = self._idempotency.get_by_client_payment(
            tenant_schema=schema,
            driver_id=driver_id,
            client_payment_id=client_payment_id,
        )

        if existing is not None:
            expected_checksum = _sha256_hex(
                '|'.join(
                    [
                        str(schema),
                        str(driver_id),
                        str(shipment_ref),
                        str(client_payment_id),
                        str(amount),
                        str(existing.expected_amount),
                        ','.join(sorted([r for r in proof_refs if r])),
                    ]
                )
            )
            try:
                self._idempotency.assert_replay_scope(
                    existing=existing,
                    tenant_schema=schema,
                    driver_id=driver_id,
                    shipment_id=shipment_ref,
                    integrity_checksum=expected_checksum,
                )
            except ValueError as exc:
                err = str(exc)
                code = (
                    'payment_replay_integrity_mismatch'
                    if 'integrity' in err
                    else 'payment_replay_scope_mismatch'
                )
                raise PaymentCollectionError(
                    str(exc),
                    code=code,
                    http_status=409,
                    message_key='mobile.payment_collection.replay_scope_mismatch',
                ) from exc
            evidence_rows = list(existing.evidence_rows.order_by('line_no'))
            reconciliation = self._reconciliation.compute_variance(
                expected_amount=existing.expected_amount,
                collected_amount=existing.amount,
            )
            return self._response_builder.build_response(
                bundle=existing,
                evidence_rows=evidence_rows,
                reconciliation=reconciliation,
                replayed=True,
            )

        shipment = self._validation.resolve_shipment(
            driver=driver,
            tenant_schema=schema,
            shipment_id=shipment_ref,
        )

        self._validation.validate_cod_eligibility(shipment=shipment)

        # Amount ceiling + variance handling.
        ceiling = self._validation.validate_amount_ceiling(
            shipment=shipment,
            amount=amount,
        )

        expected_amount = ceiling['expected_amount']  # type: ignore[assignment]
        collected_amount = ceiling['collected_amount']  # type: ignore[assignment]
        variance_detected = bool(ceiling['variance_detected'])
        variance_info = ceiling.get('variance') if isinstance(ceiling, dict) else None
        variance_amount = variance_info.get('variance_amount') if variance_info else Decimal('0.00')
        variance_type = variance_info.get('variance_type') if variance_info else 'none'

        duplicate = self._validation.validate_duplicate_payment(
            shipment=shipment,
            driver=driver,
        )
        if duplicate:
            raise PaymentCollectionError(
                'Duplicate COD payment detected.',
                code='duplicate_payment',
                http_status=409,
                message_key='mobile.payment_collection.duplicate_payment',
            )

        self._validation.validate_proof_media_paths(
            media_items=proof_media,
            tenant_schema=schema,
            driver_pk=driver_id,
            shipment_pk=shipment_ref,
        )

        # Integrity checksum for tamper-evident chaining (metadata-only).
        integrity_checksum = _sha256_hex(
            '|'.join(
                [
                    str(schema),
                    str(driver_id),
                    str(shipment_ref),
                    str(client_payment_id),
                    str(amount),
                    str(expected_amount),
                    ','.join(sorted([r for r in proof_refs if r])),
                ]
            )
        )

        variance = self._reconciliation.compute_variance(
            expected_amount=expected_amount,
            collected_amount=collected_amount,
        )

        try:
            bundle, evidence_rows, _audit = (
                self._bundle_service.create_bundle_and_evidence(
                    tenant_schema=schema,
                    driver_id=driver_id,
                    shipment_id=shipment_ref,
                    client_payment_id=client_payment_id,
                    amount=amount,
                    expected_amount=expected_amount,
                    variance_detected=variance_detected,
                    variance_amount=Decimal(str(variance_amount)),
                    variance_type=str(variance_type),
                    payment_mode=payment_mode,
                    notes=notes,
                    integrity_checksum=integrity_checksum,
                    evidence_items=proof_media,
                )
            )
            return self._response_builder.build_response(
                bundle=bundle,
                evidence_rows=evidence_rows,
                reconciliation=variance,
                replayed=False,
            )
        except Exception as exc:
            # Replay-safe race: on unique collision, reload existing bundle.
            from django.db import IntegrityError

            if isinstance(exc, IntegrityError):
                existing2 = self._idempotency.get_by_client_payment(
                    tenant_schema=schema,
                    driver_id=driver_id,
                    client_payment_id=client_payment_id,
                )
                if existing2 is None:
                    raise
                try:
                    self._idempotency.assert_replay_scope(
                        existing=existing2,
                        tenant_schema=schema,
                        driver_id=driver_id,
                        shipment_id=shipment_ref,
                        integrity_checksum=integrity_checksum,
                    )
                except ValueError as vexc:
                    code = (
                        'payment_replay_integrity_mismatch'
                        if 'integrity' in str(vexc)
                        else 'payment_replay_scope_mismatch'
                    )
                    raise PaymentCollectionError(
                        str(vexc),
                        code=code,
                        http_status=409,
                        message_key='mobile.payment_collection.replay_scope_mismatch',
                    ) from vexc
                evidence_rows2 = list(existing2.evidence_rows.order_by('line_no'))
                reconciliation2 = self._reconciliation.compute_variance(
                    expected_amount=existing2.expected_amount,
                    collected_amount=existing2.amount,
                )
                return self._response_builder.build_response(
                    bundle=existing2,
                    evidence_rows=evidence_rows2,
                    reconciliation=reconciliation2,
                    replayed=True,
                )
            raise

