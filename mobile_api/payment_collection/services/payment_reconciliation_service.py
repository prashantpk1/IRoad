"""
mobile_api/payment_collection/services/payment_reconciliation_service.py

Compute treasury variance signals for staged payment collection.
"""
from __future__ import annotations

from decimal import Decimal


class PaymentReconciliationService:
    """Detect variance between expected COD amount and submitted amount."""

    def compute_variance(
        self,
        *,
        expected_amount: Decimal,
        collected_amount: Decimal,
    ) -> dict[str, object]:
        expected_amount = Decimal(str(expected_amount))
        collected_amount = Decimal(str(collected_amount))
        variance_detected = collected_amount != expected_amount
        return {
            'variance_detected': bool(variance_detected),
            'expected_amount': expected_amount,
            'collected_amount': collected_amount,
        }

