"""Booking trip price resolution from price list overrides."""
from __future__ import annotations

from decimal import Decimal
from unittest import TestCase

from iroad_tenants.booking_trip_price import resolve_trip_booking_sell_price


class BookingTripPriceResolutionTests(TestCase):
    def setUp(self):
        self.overrides = {
            'sell': '250',
            'outbound': '90',
            'inbound': '70',
        }
        self.service_prices = {
            'sell': Decimal('100'),
            'outbound': Decimal('80'),
            'inbound': Decimal('60'),
        }

    def test_round_trip_uses_price_list_sell_price(self):
        price = resolve_trip_booking_sell_price(
            overrides_bucket=self.overrides,
            service_sell_price=self.service_prices['sell'],
            service_outbound_sell_price=self.service_prices['outbound'],
            service_inbound_sell_price=self.service_prices['inbound'],
            trip_type='Round',
            route_direction='forward',
        )
        self.assertEqual(price, Decimal('250'))

    def test_outbound_forward_uses_outbound_price(self):
        price = resolve_trip_booking_sell_price(
            overrides_bucket=self.overrides,
            service_sell_price=self.service_prices['sell'],
            service_outbound_sell_price=self.service_prices['outbound'],
            service_inbound_sell_price=self.service_prices['inbound'],
            trip_type='One-Way',
            route_direction='forward',
        )
        self.assertEqual(price, Decimal('90'))

    def test_inbound_reverse_uses_inbound_price(self):
        price = resolve_trip_booking_sell_price(
            overrides_bucket=self.overrides,
            service_sell_price=self.service_prices['sell'],
            service_outbound_sell_price=self.service_prices['outbound'],
            service_inbound_sell_price=self.service_prices['inbound'],
            trip_type='One-Way',
            route_direction='reverse',
        )
        self.assertEqual(price, Decimal('70'))

    def test_outbound_falls_back_to_service_outbound_price(self):
        price = resolve_trip_booking_sell_price(
            overrides_bucket={},
            service_sell_price=self.service_prices['sell'],
            service_outbound_sell_price=self.service_prices['outbound'],
            service_inbound_sell_price=self.service_prices['inbound'],
            trip_type='One-Way',
            route_direction='forward',
        )
        self.assertEqual(price, Decimal('80'))
