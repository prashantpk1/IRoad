"""
Tests for unified job card projection contract.
"""
from unittest.mock import MagicMock
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.job_card_projections import (
    build_movement_job_card_projection,
    build_shipment_job_card_projection,
    flatten_route_fields,
    flatten_truck_fields,
    project_operational_indicators,
)


class JobCardProjectionContractTests(SimpleTestCase):
    def test_flat_route_and_truck_helpers(self):
        route = {'summary': 'A → B', 'from_label': 'A', 'to_label': 'B'}
        flat = flatten_route_fields(route)
        self.assertEqual(flat['route_summary'], 'A → B')
        self.assertEqual(flat['from_location'], 'A')

        truck = {
            'truck_id': str(uuid4()),
            'truck_code': 'T1',
            'plate_number': 'ABC-1',
            'truck_status': 'Active',
            'sourcing_mode': 'In-Source',
        }
        tflat = flatten_truck_fields(truck)
        self.assertEqual(tflat['truck_code'], 'T1')
        self.assertEqual(tflat['plate_number'], 'ABC-1')

    def test_shipment_card_has_unified_fields(self):
        shipment = MagicMock()
        shipment.shipment_id = uuid4()
        shipment.shipment_no = 'SH-100'
        shipment.shipment_status = 'In Transit'
        shipment.order_type = 'COD'
        shipment.pod_status = 'Pending'
        shipment.collection_status = 'Pending'
        shipment.cod_amount = 50
        shipment.route_display = 'Depot → Client'
        shipment.updated_at = None
        shipment.created_at = None
        shipment.shipment_date = None
        shipment.booking = None
        shipment.truck = None
        shipment.loading_address = None
        shipment.delivery_address = None

        card = build_shipment_job_card_projection(shipment, request=None)
        self.assertEqual(card['job_type'], 'shipment')
        self.assertEqual(card['job_no'], 'SH-100')
        self.assertEqual(card['job_id'], str(shipment.shipment_id))
        self.assertIn('route_summary', card)
        self.assertIn('needs_pod', card)
        self.assertIn('indicators', card)
        self.assertIsNone(card.get('latest_action_summary'))
        self.assertEqual(card['indicators']['needs_pod'], card['needs_pod'])

    def test_movement_empty_move_card(self):
        movement = MagicMock()
        movement.movement_id = uuid4()
        movement.movement_no = 'MV-22'
        movement.status = 'Scheduled'
        movement.movement_source = 'empty'
        movement.empty_move_reason = 'Depot return'
        movement.updated_at = None
        movement.created_at = None
        movement.movement_date = None
        movement.shipment = None
        movement.truck = None
        movement.from_location_point = None
        movement.to_location_point = None

        card = build_movement_job_card_projection(movement, request=None)
        self.assertEqual(card['job_type'], 'movement')
        self.assertEqual(card['job_no'], 'MV-22')
        self.assertTrue(card['is_empty_move'])
        self.assertEqual(card['pod_status'], '')

    def test_operational_indicators_shipment(self):
        shipment = MagicMock()
        shipment.shipment_status = 'In Transit'
        shipment.pod_status = 'Pending'
        shipment.order_type = 'COD'
        shipment.collection_status = 'Pending'
        shipment.cod_amount = 10
        flags = project_operational_indicators(job_type='shipment', shipment=shipment)
        self.assertTrue(flags['is_active'])
