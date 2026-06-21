"""Tests for movement location projection with Google Places snapshots."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase, RequestFactory

from mobile_api.job_detail.projections.job_location_projection import (
    build_movement_location_block,
    serialize_location_point,
)


class MovementLocationProjectionTests(SimpleTestCase):
    def test_serialize_location_point_places_only(self):
        result = serialize_location_point(
            None,
            address='King Abdulaziz Rd, Jeddah',
            latitude='21.5433',
            longitude='39.1728',
        )
        self.assertEqual(result['display_name'], 'King Abdulaziz Rd, Jeddah')
        self.assertEqual(result['label'], 'King Abdulaziz Rd, Jeddah')
        self.assertEqual(result['latitude'], '21.5433')
        self.assertEqual(result['longitude'], '39.1728')
        self.assertIn('maps.google.com', result['map_link'])

    def test_places_address_overrides_location_master_label(self):
        location = SimpleNamespace(
            location_id='11111111-1111-1111-1111-111111111111',
            location_code='LC-001',
            location_name_english='Jeddah',
            location_name_arabic='Jeddah',
            display_label='Jeddah',
            province='Makkah',
        )
        result = serialize_location_point(
            location,
            address='Exact depot gate, Jeddah',
            latitude='21.5433',
            longitude='39.1728',
        )
        self.assertEqual(result['display_name'], 'Exact depot gate, Jeddah')
        self.assertEqual(result['location_code'], 'LC-001')

    def test_build_movement_location_block_uses_tml_places_fields(self):
        movement = SimpleNamespace(
            shipment=None,
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='',
            from_location_address='From depot',
            to_location_address='To workshop',
            from_latitude='24.7136',
            from_longitude='46.6753',
            to_latitude='21.4858',
            to_longitude='39.1925',
            _state=SimpleNamespace(fields_cache={}),
        )
        block = build_movement_location_block(movement, request=RequestFactory().get('/'))
        self.assertEqual(block['pickup_address']['display_name'], 'From depot')
        self.assertEqual(block['drop_address']['latitude'], '21.4858')
