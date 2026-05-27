"""
mobile_api/payment_collection/services/payment_idempotency_service.py

DB-backed idempotency for payment collection staging bundles.
"""
from __future__ import annotations

from typing import Any

from django.db import IntegrityError

from mobile_api.payment_collection.models import (
    PaymentCollectionBundle,
)


class PaymentIdempotencyService:
    """Replay-safe bundle lookup and scope checks."""

    def get_by_client_payment(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        client_payment_id: str,
    ) -> PaymentCollectionBundle | None:
        return (
            PaymentCollectionBundle.objects.filter(
                tenant_schema=(tenant_schema or '').strip(),
                driver_id=(driver_id or '').strip(),
                client_payment_id=(client_payment_id or '').strip(),
            ).first()
        )

    def assert_replay_scope(
        self,
        *,
        existing: PaymentCollectionBundle,
        tenant_schema: str,
        driver_id: str,
        shipment_id: str,
        integrity_checksum: str | None = None,
    ) -> None:
        if (existing.tenant_schema or '').strip() != (tenant_schema or '').strip():
            raise ValueError('payment_replay_tenant_scope_mismatch')
        if (existing.driver_id or '').strip() != (driver_id or '').strip():
            raise ValueError('payment_replay_driver_scope_mismatch')
        if (existing.shipment_id or '').strip() != (shipment_id or '').strip():
            raise ValueError('payment_replay_shipment_scope_mismatch')
        if integrity_checksum is not None:
            # Treat checksum mismatch as tamper / body divergence for an otherwise-idempotent key.
            if str(existing.integrity_checksum or '').strip() != str(integrity_checksum or '').strip():
                raise ValueError('payment_replay_integrity_mismatch')

    def try_create_bundle_race_safe(
        self,
        *,
        tenant_schema: str,
        driver_id: str,
        client_payment_id: str,
        shipment_id: str,
        create_kwargs: dict[str, Any],
    ) -> tuple[PaymentCollectionBundle, bool]:
        """
        Attempt bundle creation. On unique collision, reload existing.
        """
        try:
            bundle = PaymentCollectionBundle.objects.create(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                shipment_id=shipment_id,
                client_payment_id=client_payment_id,
                **create_kwargs,
            )
            return bundle, True
        except IntegrityError:
            existing = self.get_by_client_payment(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                client_payment_id=client_payment_id,
            )
            if existing is None:
                raise
            self.assert_replay_scope(
                existing=existing,
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                shipment_id=shipment_id,
            )
            return existing, False

