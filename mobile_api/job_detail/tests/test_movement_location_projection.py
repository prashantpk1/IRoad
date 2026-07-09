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
        self.assertEqual(block['pickup_address']['from_address'], 'From depot')
        self.assertEqual(block['drop_address']['latitude'], '21.4858')
        self.assertEqual(block['drop_address']['to_address'], 'To workshop')

    def test_empty_move_pickup_prefers_from_address_over_coords(self):
        movement = SimpleNamespace(
            shipment=None,
            movement_source='empty',
            empty_move_reason='maintenance',
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='',
            from_location_address=(
                'Oxydarshanam Tower A, Vasna - Bhayli Main Rd, Vadodara, Gujarat, India'
            ),
            to_location_address='',
            from_latitude='22.29366',
            from_longitude='73.13717833333334',
            to_latitude='',
            to_longitude='',
            _state=SimpleNamespace(fields_cache={}),
        )
        block = build_movement_location_block(movement, request=RequestFactory().get('/'))
        pickup = block['pickup_address']
        self.assertEqual(
            pickup['from_address'],
            'Oxydarshanam Tower A, Vasna - Bhayli Main Rd, Vadodara, Gujarat, India',
        )
        self.assertEqual(
            pickup['display_name'],
            'Oxydarshanam Tower A, Vasna - Bhayli Main Rd, Vadodara, Gujarat, India',
        )
        self.assertEqual(pickup['latitude'], '22.29366')
        drop = block['drop_address']
        self.assertEqual(drop['latitude'], '')
        self.assertEqual(drop['longitude'], '')
        self.assertEqual(drop['location_capture_mode'], 'gps')
        self.assertTrue(drop['gps_capture_required'])

    def test_empty_move_drop_shows_planned_to_address_without_gps(self):
        movement = SimpleNamespace(
            shipment=None,
            movement_source='empty',
            empty_move_reason='maintenance',
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='',
            from_location_address='Departure point',
            to_location_address='Workshop destination',
            from_latitude='22.29366',
            from_longitude='73.13717833333334',
            to_latitude='',
            to_longitude='',
            _state=SimpleNamespace(fields_cache={}),
        )
        block = build_movement_location_block(movement, request=RequestFactory().get('/'))
        drop = block['drop_address']
        self.assertEqual(drop['to_address'], 'Workshop destination')
        self.assertEqual(drop['display_name'], 'Workshop destination')
        self.assertEqual(drop['latitude'], '')
        self.assertEqual(drop['longitude'], '')
        self.assertEqual(drop['location_capture_mode'], 'gps')
        self.assertTrue(drop['gps_capture_required'])

    def test_empty_move_drop_includes_destination_gps_when_stored(self):
        movement = SimpleNamespace(
            shipment=None,
            movement_source='empty',
            empty_move_reason='maintenance',
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='https://maps.google.com/?q=21.4858,39.1925',
            from_location_address='Departure point',
            to_location_address='Workshop destination',
            from_latitude='22.29366',
            from_longitude='73.13717833333334',
            to_latitude='21.4858',
            to_longitude='39.1925',
            _state=SimpleNamespace(fields_cache={}),
        )
        block = build_movement_location_block(movement, request=RequestFactory().get('/'))
        drop = block['drop_address']
        self.assertEqual(drop['to_address'], 'Workshop destination')
        self.assertEqual(drop['latitude'], '21.4858')
        self.assertEqual(drop['longitude'], '39.1925')
        self.assertEqual(drop['location_capture_mode'], 'gps')
        self.assertIn('maps.google.com', drop['map_link'])

    def test_empty_move_delivery_hidden_before_departure(self):
        movement = SimpleNamespace(
            shipment=None,
            movement_source='empty',
            empty_move_reason='maintenance',
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='',
            from_location_address='Departure point',
            to_location_address='Workshop destination',
            from_latitude='22.29366',
            from_longitude='73.13717833333334',
            to_latitude='21.4858',
            to_longitude='39.1925',
            _state=SimpleNamespace(fields_cache={}),
        )
        block = build_movement_location_block(
            movement,
            request=RequestFactory().get('/'),
            movement_logs=[],
        )
        self.assertEqual(block['delivery_address'], {})
        self.assertEqual(block['drop_address'], {})

    def test_empty_move_delivery_address_after_departure(self):
        movement = SimpleNamespace(
            shipment=None,
            movement_source='empty',
            empty_move_reason='maintenance',
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='https://maps.google.com/?q=22.29366,73.13717833333334',
            from_location_address='Departure point',
            to_location_address=(
                'Oxydarshanam Tower A, B 306, Vasna - Bhayli Main Rd, Vadodara, Gujarat, India'
            ),
            from_latitude='22.29366',
            from_longitude='73.13717833333334',
            to_latitude='22.29400',
            to_longitude='73.13800',
            _state=SimpleNamespace(fields_cache={}),
        )
        departure_log = SimpleNamespace(
            operation_action=SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                arabic_label='Departure',
                movement_status_impact='',
                shipment_status_impact='',
                sequence_category='empty_move',
            ),
        )
        block = build_movement_location_block(
            movement,
            request=RequestFactory().get('/'),
            movement_logs=[departure_log],
        )
        delivery = block['delivery_address']
        self.assertEqual(
            delivery['to_address'],
            'Oxydarshanam Tower A, B 306, Vasna - Bhayli Main Rd, Vadodara, Gujarat, India',
        )
        self.assertEqual(delivery['latitude'], '22.29400')
        self.assertEqual(delivery['longitude'], '73.13800')
        self.assertEqual(delivery['location_capture_mode'], 'gps')
        self.assertIn('maps.google.com', delivery['map_link'])
        self.assertEqual(block['drop_address'], delivery)

    def test_delivery_not_copied_from_start_when_to_matches_departure(self):
        movement = SimpleNamespace(
            shipment=None,
            movement_source='empty',
            empty_move_reason='maintenance',
            from_location_point_id=None,
            to_location_point_id=None,
            from_location_map_link='',
            to_location_map_link='',
            from_location_address='Same place',
            to_location_address='Same place',
            from_latitude='22.29366',
            from_longitude='73.13717833333334',
            to_latitude='22.29366',
            to_longitude='73.13717833333334',
            _state=SimpleNamespace(fields_cache={}),
        )
        departure_log = SimpleNamespace(
            operation_action=SimpleNamespace(
                action_code='OA-0015',
                english_label='Departure',
                arabic_label='Departure',
                movement_status_impact='',
                shipment_status_impact='',
                sequence_category='empty_move',
            ),
        )
        block = build_movement_location_block(
            movement,
            request=RequestFactory().get('/'),
            movement_logs=[departure_log],
        )
        delivery = block['delivery_address']
        self.assertTrue(delivery.get('awaiting_arrival_gps'))
        self.assertEqual(delivery.get('display_name'), '')
        self.assertNotIn('to_address', delivery)
        self.assertEqual(delivery.get('latitude'), '')
