"""
mobile_api/payment_collection/dto/payment_response_builder.py

Build response payload for payment collection staging.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any


class PaymentResponseBuilder:
    def build_response(
        self,
        *,
        bundle: Any,
        evidence_rows: list[Any],
        reconciliation: dict[str, Any],
        replayed: bool,
    ) -> dict[str, Any]:
        proof_media = [
            {
                'media_type': getattr(r, 'media_type', '') or '',
                'file_ref': getattr(r, 'file_ref', '') or '',
                'file_name': getattr(r, 'file_name', '') or '',
                'immutable': bool(getattr(r, 'immutable', True)),
            }
            for r in evidence_rows
        ]

        payment_bundle = {
            'bundle_id': str(getattr(bundle, 'id', '') or ''),
            'client_payment_id': getattr(bundle, 'client_payment_id', '') or '',
            'shipment_id': getattr(bundle, 'shipment_id', '') or '',
            'driver_id': getattr(bundle, 'driver_id', '') or '',
            'amount': str(getattr(bundle, 'amount', Decimal('0'))),
            'expected_amount': str(getattr(bundle, 'expected_amount', Decimal('0'))),
            'variance_detected': bool(getattr(bundle, 'variance_detected', False)),
            'payment_mode': getattr(bundle, 'payment_mode', '') or '',
            'notes': getattr(bundle, 'notes', '') or '',
            'media_count': len(proof_media),
            'proof_media': proof_media,
            'replayed': bool(replayed),
        }

        return {
            'payment_bundle': payment_bundle,
            'reconciliation': {
                'variance_detected': bool(reconciliation.get('variance_detected')),
                'expected_amount': str(reconciliation.get('expected_amount')),
                'collected_amount': str(reconciliation.get('collected_amount')),
            },
            'next_step': {
                'requires_execute_action': True,
            },
        }

