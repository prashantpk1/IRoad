"""Tests for order_type normalization."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from mobile_api.helpers.order_type import resolve_order_type_text


class OrderTypeHelperTests(SimpleTestCase):
    def test_cod_from_shipment(self):
        shipment = SimpleNamespace(order_type='COD')
        self.assertEqual(resolve_order_type_text(shipment=shipment), 'COD')

    def test_credit_from_shipment(self):
        shipment = SimpleNamespace(order_type='Credit')
        self.assertEqual(resolve_order_type_text(shipment=shipment), 'Credit')

    def test_fallback_booking(self):
        booking = SimpleNamespace(order_type='COD')
        self.assertEqual(resolve_order_type_text(booking=booking), 'COD')

    def test_non_cod_maps_to_credit(self):
        shipment = SimpleNamespace(order_type='SA')
        self.assertEqual(resolve_order_type_text(shipment=shipment), 'Credit')
