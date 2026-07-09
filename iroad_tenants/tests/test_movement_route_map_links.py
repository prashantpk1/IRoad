"""GPS route evidence on truck movement logs (empty move)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.movement_ops import (
    apply_movement_endpoint_gps,
    apply_movement_route_map_links,
    sync_movement_route_evidence_from_action_log,
)


class MovementRouteMapLinkTests(SimpleTestCase):
    def test_apply_movement_route_map_links_sets_from_and_to(self):
        movement = SimpleNamespace(
            from_location_map_link='',
            to_location_map_link='',
            from_location_address='',
            to_location_address='',
            from_latitude='',
            from_longitude='',
            to_latitude='',
            to_longitude='',
            save=MagicMock(),
        )

        apply_movement_route_map_links(
            movement,
            from_latitude='24.7136',
            from_longitude='46.6753',
            to_latitude='21.4858',
            to_longitude='39.1925',
            from_address='Depot A',
            to_address='Depot B',
        )

        self.assertIn('24.7136', movement.from_location_map_link)
        self.assertIn('21.4858', movement.to_location_map_link)
        self.assertEqual(movement.from_location_address, 'Depot A')
        self.assertEqual(movement.to_latitude, '21.4858')
        movement.save.assert_called()

    def test_duplicate_arrival_cleared_when_departure_stamped(self):
        movement = SimpleNamespace(
            from_location_map_link='',
            to_location_map_link='https://maps.google.com/?q=24.7136,46.6753',
            from_location_address='',
            to_location_address='Depot A',
            from_latitude='',
            from_longitude='',
            to_latitude='24.7136',
            to_longitude='46.6753',
            save=MagicMock(),
        )
        apply_movement_endpoint_gps(
            movement,
            'from',
            latitude='24.7136',
            longitude='46.6753',
            address='Depot A',
            overwrite=True,
        )
        self.assertEqual(movement.from_latitude, '24.7136')
        self.assertEqual(movement.to_latitude, '')
        self.assertEqual(movement.to_location_address, '')

    def test_planned_distinct_arrival_preserved_when_departure_stamped(self):
        movement = SimpleNamespace(
            from_location_map_link='',
            to_location_map_link='https://maps.google.com/?q=21.4858,39.1925',
            from_location_address='Depot A',
            to_location_address='Workshop B',
            from_latitude='',
            from_longitude='',
            to_latitude='21.4858',
            to_longitude='39.1925',
            save=MagicMock(),
        )
        apply_movement_endpoint_gps(
            movement,
            'from',
            latitude='24.7136',
            longitude='46.6753',
            address='Depot A',
            overwrite=True,
        )
        self.assertEqual(movement.to_latitude, '21.4858')
        self.assertEqual(movement.to_location_address, 'Workshop B')

    def test_apply_movement_endpoint_gps_from_only(self):
        movement = SimpleNamespace(
            from_location_map_link='',
            from_location_address='',
            from_latitude='',
            from_longitude='',
            to_location_map_link='',
            to_location_address='',
            to_latitude='',
            to_longitude='',
            save=MagicMock(),
        )
        apply_movement_endpoint_gps(
            movement,
            'from',
            latitude='24.7136',
            longitude='46.6753',
            address='Depot A',
        )
        self.assertEqual(movement.from_latitude, '24.7136')
        self.assertEqual(movement.from_location_address, 'Depot A')
        self.assertEqual(movement.to_latitude, '')

    def test_sync_from_on_em1_start_action(self):
        movement = SimpleNamespace(
            from_location_map_link='',
            from_location_address='',
            from_latitude='',
            from_longitude='',
            to_location_map_link='',
            to_location_address='',
            to_latitude='',
            to_longitude='',
            save=MagicMock(),
        )
        action = SimpleNamespace(
            action_code='EM1',
            english_label='Start Movement',
            movement_status_impact='In_Progress',
        )
        action_log = SimpleNamespace(
            truck_movement=movement,
            shipment_id=None,
            operation_action=action,
            latitude='24.7136',
            longitude='46.6753',
            map_link='',
            _route_location_address='Depot A',
        )

        sync_movement_route_evidence_from_action_log(action_log)

        self.assertIn('24.7136', movement.from_location_map_link)
        self.assertEqual(movement.from_latitude, '24.7136')
        self.assertEqual(movement.from_location_address, 'Depot A')
        self.assertEqual(movement.to_location_map_link, '')

    def test_sync_does_not_set_to_on_em3_arrival(self):
        movement = SimpleNamespace(
            from_location_map_link='https://maps.google.com/?q=24,46',
            from_location_address='',
            from_latitude='24.7136',
            from_longitude='46.6753',
            to_location_map_link='',
            to_location_address='',
            to_latitude='',
            to_longitude='',
            save=MagicMock(),
        )
        action = SimpleNamespace(
            action_code='EM3',
            english_label='Arrival At Destination',
            movement_status_impact='',
        )
        action_log = SimpleNamespace(
            truck_movement=movement,
            shipment_id=None,
            operation_action=action,
            latitude='21.4858',
            longitude='39.1925',
            map_link='https://maps.google.com/?q=21.4858,39.1925',
            _route_location_address='',
        )

        sync_movement_route_evidence_from_action_log(action_log)

        self.assertEqual(movement.to_location_map_link, '')

    def test_sync_departure_stamps_destination_address_text(self):
        movement = SimpleNamespace(
            movement_source='empty',
            from_location_map_link='https://maps.google.com/?q=21.5433,39.1728',
            from_location_address='Jeddah',
            from_latitude='21.5433',
            from_longitude='39.1728',
            to_location_map_link='',
            to_location_address='',
            to_latitude='',
            to_longitude='',
            save=MagicMock(),
        )
        action = SimpleNamespace(
            action_code='OA-0015',
            english_label='Departure',
            movement_status_impact='',
            sequence_category='empty_move',
            sequence_number=2,
        )
        action_log = SimpleNamespace(
            truck_movement=movement,
            shipment_id=None,
            operation_action=action,
            latitude='21.5433',
            longitude='39.1728',
            map_link='',
            _route_location_address='Industrial Area, Makkah, Saudi Arabia',
        )

        sync_movement_route_evidence_from_action_log(action_log)

        self.assertEqual(
            movement.to_location_address,
            'Industrial Area, Makkah, Saudi Arabia',
        )
        self.assertEqual(movement.to_latitude, '')
        self.assertEqual(movement.to_longitude, '')

    def test_sync_to_on_em4_complete_action(self):
        movement = SimpleNamespace(
            from_location_map_link='https://maps.google.com/?q=24,46',
            from_location_address='Start',
            from_latitude='24.7136',
            from_longitude='46.6753',
            to_location_map_link='',
            to_location_address='',
            to_latitude='',
            to_longitude='',
            save=MagicMock(),
        )
        action = SimpleNamespace(
            action_code='EM4',
            english_label='Complete Movement',
            movement_status_impact='Completed',
        )
        action_log = SimpleNamespace(
            truck_movement=movement,
            shipment_id=None,
            operation_action=action,
            latitude='21.4858',
            longitude='39.1925',
            map_link='https://maps.google.com/?q=21.4858,39.1925',
            _route_location_address='Industrial Area',
        )

        sync_movement_route_evidence_from_action_log(action_log)

        self.assertIn('21.4858', movement.to_location_map_link)
        self.assertEqual(movement.to_latitude, '21.4858')
        self.assertEqual(movement.to_location_address, 'Industrial Area')
