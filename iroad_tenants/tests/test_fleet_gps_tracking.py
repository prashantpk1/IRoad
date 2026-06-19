"""Tests for fleet GPS surveillance payload builder."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from iroad_tenants.fleet_gps_tracking import _coords_from_log, build_google_maps_link


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