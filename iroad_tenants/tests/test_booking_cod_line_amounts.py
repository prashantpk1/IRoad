"""Booking line COD amount normalization for Credit vs COD order types."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from iroad_tenants.views import _tenant_booking_normalize_cod_line_amounts


def _request(**post):
    return SimpleNamespace(POST=post)


class BookingCodLineAmountTests(TestCase):
    def test_credit_order_zeros_cod_line_amounts(self):
        outbound, backload = _tenant_booking_normalize_cod_line_amounts(
            _request(
                booking_line_cod_amount_1='500',
                booking_line_cod_amount_2='200',
            ),
            trip_type='One-Way',
            order_type='Credit',
            sell_price=Decimal('1400'),
        )
        self.assertEqual(outbound, Decimal('0'))
        self.assertEqual(backload, Decimal('0'))

    def test_cod_one_way_defaults_to_sell_price_when_empty(self):
        outbound, backload = _tenant_booking_normalize_cod_line_amounts(
            _request(booking_line_cod_amount_1=''),
            trip_type='One-Way',
            order_type='COD',
            sell_price=Decimal('1400'),
        )
        self.assertEqual(outbound, Decimal('1400'))
        self.assertEqual(backload, Decimal('0'))

    def test_cod_one_way_keeps_user_amount(self):
        outbound, backload = _tenant_booking_normalize_cod_line_amounts(
            _request(booking_line_cod_amount_1='900'),
            trip_type='One-Way',
            order_type='COD',
            sell_price=Decimal('1400'),
        )
        self.assertEqual(outbound, Decimal('900'))
        self.assertEqual(backload, Decimal('0'))
