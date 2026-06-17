"""Directional route chip helpers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from iroad_tenants.views import (
    _tenant_route_chip_arrow_variant,
    _tenant_route_chip_from_context,
    _tenant_shipment_route_chip,
)


class RouteChipArrowVariantTests(TestCase):
    def test_outbound_default(self):
        self.assertEqual(_tenant_route_chip_arrow_variant(), 'outbound')

    def test_backload_is_inbound(self):
        self.assertEqual(
            _tenant_route_chip_arrow_variant(booking_item_type='Backload'),
            'inbound',
        )

    def test_round_booking_without_line_type(self):
        self.assertEqual(
            _tenant_route_chip_arrow_variant(trip_type='Round'),
            'round',
        )


class RouteChipFromContextTests(TestCase):
    def test_parses_to_separator(self):
        chip = _tenant_route_chip_from_context(route_display='jeddah To Makkah')
        self.assertIsNotNone(chip)
        self.assertEqual(chip['origin'], 'jeddah')
        self.assertEqual(chip['destination'], 'Makkah')
        self.assertEqual(chip['arrow_variant'], 'outbound')

    def test_backload_uses_red_arrow(self):
        chip = _tenant_route_chip_from_context(
            route_display='Makkah To jeddah',
            booking_item_type='Backload',
        )
        self.assertEqual(chip['arrow_variant'], 'inbound')
        self.assertEqual(chip['origin'], 'Makkah')
        self.assertEqual(chip['destination'], 'jeddah')


class ShipmentRouteChipTests(TestCase):
    def test_shipment_chip_from_route_display(self):
        shipment = SimpleNamespace(
            booking_id=None,
            route_display='jeddah To Makkah',
            booking_item_type='Outbound',
            trip_type='Round',
        )
        chip = _tenant_shipment_route_chip(shipment)
        self.assertEqual(chip['origin'], 'jeddah')
        self.assertEqual(chip['destination'], 'Makkah')
        self.assertEqual(chip['arrow_variant'], 'outbound')
