"""Tests for fleet GPS surveillance payload builder."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from iroad_tenants.fleet_gps_tracking import (
    _coords_from_log,
    _resolve_shipment_route_context,
    build_google_maps_link,
)


class FleetGpsCoordTests(TestCase):
    def test_coords_from_latitude_longitude(self):
        log = SimpleNamespace(latitude='24.7136', longitude='46.6753', map_link='')
        self.assertEqual(_coords_from_log(log), (24.7136, 46.6753))

    def test_coords_from_map_link(self):
        log = SimpleNamespace(
            latitude='',
            longitude='',
            map_link='https://maps.google.com/?q=21.4858,39.1925',
        )
        self.assertEqual(_coords_from_log(log), (21.4858, 39.1925))

    def test_coords_empty_when_missing(self):
        log = SimpleNamespace(latitude='', longitude='', map_link='')
        self.assertIsNone(_coords_from_log(log))

    def test_build_google_maps_link(self):
        self.assertEqual(
            build_google_maps_link('24.7', '46.6', ''),
            'https://maps.google.com/?q=24.7,46.6',
        )
        self.assertEqual(
            build_google_maps_link('', '', 'https://maps.example/x'),
            'https://maps.example/x',
        )


class FleetGpsRouteContextTests(TestCase):
    def _address(self, label: str, lat: float, lng: float):
        return SimpleNamespace(
            display_name=label,
            english_label=label,
            arabic_label='',
            map_link=f'https://maps.google.com/?q={lat},{lng}',
        )

    def test_outbound_leg_uses_forward_route_labels_and_address_pins(self):
        shipment = SimpleNamespace(
            booking_item_type='Outbound',
            route_display='',
            loading_address=self._address('Jeddah Site', 21.5433, 39.1728),
            delivery_address=self._address('Makkah Site', 21.3891, 39.8579),
            booking=SimpleNamespace(
                trip_type='Round',
                route_direction='forward',
                route_display='',
                loading_address=None,
                delivery_address=None,
                route=SimpleNamespace(
                    route_id='route-1',
                    route_label='Jeddah — Makkah',
                    origin_point=SimpleNamespace(display_label='Jeddah'),
                    destination_point=SimpleNamespace(display_label='Makkah'),
                ),
            ),
        )
        ctx = _resolve_shipment_route_context(shipment)
        self.assertEqual(ctx['departure_label'], 'Jeddah')
        self.assertEqual(ctx['arrival_label'], 'Makkah')
        self.assertEqual(ctx['route_start'], {'lat': 21.5433, 'lng': 39.1728})
        self.assertEqual(ctx['route_end'], {'lat': 21.3891, 'lng': 39.8579})

    def test_backload_leg_reverses_route_and_swaps_address_pins(self):
        shipment = SimpleNamespace(
            booking_item_type='Backload',
            route_display='',
            loading_address=self._address('Jeddah Site', 21.5433, 39.1728),
            delivery_address=self._address('Makkah Site', 21.3891, 39.8579),
            booking=SimpleNamespace(
                trip_type='Round',
                route_direction='forward',
                route_display='',
                loading_address=None,
                delivery_address=None,
                route=SimpleNamespace(
                    route_id='route-1',
                    route_label='Jeddah — Makkah',
                    origin_point=SimpleNamespace(display_label='Jeddah'),
                    destination_point=SimpleNamespace(display_label='Makkah'),
                ),
            ),
        )
        ctx = _resolve_shipment_route_context(shipment)
        self.assertEqual(ctx['departure_label'], 'Makkah')
        self.assertEqual(ctx['arrival_label'], 'Jeddah')
        self.assertEqual(ctx['route_start'], {'lat': 21.3891, 'lng': 39.8579})
        self.assertEqual(ctx['route_end'], {'lat': 21.5433, 'lng': 39.1728})
