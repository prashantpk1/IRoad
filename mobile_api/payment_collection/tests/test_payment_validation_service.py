"""Payment validation rules for driver COD collection."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from mobile_api.payment_collection.exceptions import PaymentCollectionError
from mobile_api.payment_collection.services.payment_validation_service import (
    PaymentValidationService,
)


class PaymentValidationServiceTests(TestCase):
    def test_blocks_amount_below_minimum(self):
        shipment = SimpleNamespace(cod_amount=Decimal('100.00'))
        with self.assertRaises(PaymentCollectionError) as exc:
            PaymentValidationService().validate_amount_ceiling(
                shipment=shipment,
                amount=Decimal('99.99'),
            )
        self.assertEqual(exc.exception.code, 'amount_below_minimum')

    def test_allows_exact_and_over_collection(self):
        shipment = SimpleNamespace(cod_amount=Decimal('100.00'))
        service = PaymentValidationService()

        exact = service.validate_amount_ceiling(
            shipment=shipment,
            amount=Decimal('100.00'),
        )
        self.assertFalse(exact['variance_detected'])

        over = service.validate_amount_ceiling(
            shipment=shipment,
            amount=Decimal('120.00'),
        )
        self.assertTrue(over['variance_detected'])
        self.assertEqual(over['variance']['variance_type'], 'over')
