"""Symmetric round-trip endpoint resolution (outbound + backload)."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.booking_endpoint_addresses import (
    leg_is_backload_line,
    resolve_booking_endpoint_addresses,
    resolve_leg_endpoint_addresses,
)


def _address(label: str, *, city: str = ''):
    return SimpleNamespace(
        english_label=label,
        arabic_label='',
        display_name=label,
        address_id=uuid4(),
        address_code='AD',
        address_category='',
        address_line_1='',
        address_line_2='',
        city=city or label,
        province='',
        district='',
        street='',
        building_no='',
        postal_code='',
        map_link='',
        contact_name='',
        mobile_no_1='',
        mobile_no_2='',
        site_instructions='',
    )


def _round_booking_with_site_addresses():
    return SimpleNamespace(
        trip_type='Round',
        route=SimpleNamespace(
            origin_point=SimpleNamespace(
                display_label='Jeddah',
                location_name_english='Jeddah',
                location_name_arabic='',
                location_id=uuid4(),
                location_code='JED',
                province='',
            ),
            destination_point=SimpleNamespace(
                display_label='Makkah',
                location_name_english='Makkah',
                location_name_arabic='',
                location_id=uuid4(),
                location_code='MKK',
                province='',
            ),
        ),
        loading_address=_address('Industrial City Phase 1, Jeddah', city='Jeddah'),
        delivery_address=_address('Zamzam Distribution Center, Mecca', city='Mecca'),
    )


class BookingEndpointAddressesTests(SimpleTestCase):
    def test_outbound_leg_uses_loading_then_delivery_fk(self):
        booking = _round_booking_with_site_addresses()
        pickup, drop = resolve_booking_endpoint_addresses(
            booking,
            leg_is_backload=False,
        )
        self.assertEqual(pickup['label'], 'Industrial City Phase 1, Jeddah')
        self.assertEqual(drop['label'], 'Zamzam Distribution Center, Mecca')

    def test_backload_leg_swaps_delivery_then_loading_fk(self):
        booking = _round_booking_with_site_addresses()
        pickup, drop = resolve_booking_endpoint_addresses(
            booking,
            leg_is_backload=True,
        )
        self.assertEqual(pickup['label'], 'Zamzam Distribution Center, Mecca')
        self.assertEqual(drop['label'], 'Industrial City Phase 1, Jeddah')

    def test_shipment_line_type_selects_leg_direction(self):
        booking = _round_booking_with_site_addresses()
        outbound_pickup, outbound_drop = resolve_leg_endpoint_addresses(
            booking,
            booking_item_type='Outbound',
        )
        backload_pickup, backload_drop = resolve_leg_endpoint_addresses(
            booking,
            booking_item_type='Backload',
        )
        self.assertEqual(outbound_pickup['label'], 'Industrial City Phase 1, Jeddah')
        self.assertEqual(outbound_drop['label'], 'Zamzam Distribution Center, Mecca')
        self.assertEqual(backload_pickup['label'], 'Zamzam Distribution Center, Mecca')
        self.assertEqual(backload_drop['label'], 'Industrial City Phase 1, Jeddah')

    def test_leg_is_backload_line(self):
        self.assertTrue(leg_is_backload_line('Backload'))
        self.assertTrue(leg_is_backload_line('Inbound'))
        self.assertFalse(leg_is_backload_line('Outbound'))
