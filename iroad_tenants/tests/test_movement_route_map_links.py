"""GPS route evidence on truck movement logs (empty move)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.movement_ops import (
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
        movement.save.assert_called_once()

    def test_sync_from_link_on_em1_start_action(self):
        movement = SimpleNamespace(
            from_location_map_link='',
            to_location_map_link='',
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
        )

        sync_movement_route_evidence_from_action_log(action_log)

        self.assertIn('24.7136', movement.from_location_map_link)
        self.assertEqual(movement.to_location_map_link, '')
        movement.save.assert_called_once()

    def test_sync_to_link_on_em3_arrival_action(self):
        movement = SimpleNamespace(
            from_location_map_link='https://maps.google.com/?q=24,46',
            to_location_map_link='',
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
        )

        sync_movement_route_evidence_from_action_log(action_log)

        self.assertIn('21.4858', movement.to_location_map_link)
        movement.save.assert_called_once()
