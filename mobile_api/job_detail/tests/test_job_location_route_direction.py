"""Route direction / backload leg display tests."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from mobile_api.job_detail.projections.job_location_projection import serialize_route


class SerializeRouteDirectionTests(SimpleTestCase):
    def test_reverse_booking_direction_swaps_route_endpoints(self):
        booking = SimpleNamespace(
            route_direction='reverse',
            route_display='jeddah To Makkah',
            route=SimpleNamespace(
                route_label='jeddah — Makkah',
                route_code='RT-1',
                route_type='Domestic',
                route_id='route-1',
                origin_point=SimpleNamespace(
                    display_label='jeddah',
                    location_name_english='jeddah',
                    location_name_arabic='',
                ),
                destination_point=SimpleNamespace(
                    display_label='Makkah',
                    location_name_english='Makkah',
                    location_name_arabic='',
                ),
            ),
        )
        route = serialize_route(booking=booking)
        self.assertEqual(route['route_display_start'], 'Makkah')
        self.assertEqual(route['route_display_end'], 'jeddah')
        self.assertEqual(route['route_direction'], 'reverse')

    def test_backload_shipment_forces_reverse_route(self):
        shipment = SimpleNamespace(
            booking_item_type='Backload',
            route_display='Makkah To jeddah',
        )
        booking = SimpleNamespace(
            route_direction='forward',
            route_display='jeddah To Makkah',
            route=SimpleNamespace(
                route_label='',
                route_code='RT-1',
                route_type='Domestic',
                route_id='route-1',
                origin_point=SimpleNamespace(
                    display_label='jeddah',
                    location_name_english='jeddah',
                    location_name_arabic='',
                ),
                destination_point=SimpleNamespace(
                    display_label='Makkah',
                    location_name_english='Makkah',
                    location_name_arabic='',
                ),
            ),
        )
        route = serialize_route(shipment=shipment, booking=booking)
        self.assertEqual(route['route_display_start'], 'Makkah')
        self.assertEqual(route['route_display_end'], 'jeddah')
