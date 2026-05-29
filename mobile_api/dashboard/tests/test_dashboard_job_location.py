"""Dashboard route + address projection tests."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.dashboard.dto.dashboard_response_builder import (
    DashboardResponseBuilder,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.projections.shipment_projection import (
    build_active_shipment_slice,
)


class DashboardJobLocationTests(SimpleTestCase):
    def test_active_shipment_slice_includes_route_and_addresses(self):
        pickup_id = uuid4()
        shipment_id = uuid4()
        shipment = SimpleNamespace(
            pk=shipment_id,
            shipment_id=shipment_id,
            shipment_no='SH-100',
            order_type='COD',
            booking_item_type='Outbound',
            shipment_status='In Transit',
            trip_type='One-Way',
            route_display='Route A',
            loading_address=SimpleNamespace(
                address_id=pickup_id,
                address_code='P1',
                display_name='Warehouse',
                english_label='Warehouse',
                arabic_label='',
                address_category='Pickup Address',
                address_line_1='Line 1',
                address_line_2='',
                city='Jeddah',
                province='Makkah',
                district='',
                street='',
                building_no='',
                postal_code='',
                map_link='https://maps.example/pickup',
                contact_name='',
                mobile_no_1='',
                mobile_no_2='',
                site_instructions='',
            ),
            delivery_address=SimpleNamespace(
                address_id=uuid4(),
                address_code='D1',
                display_name='Customer',
                english_label='Customer',
                arabic_label='',
                address_category='Delivery Address',
                address_line_1='Line 2',
                address_line_2='',
                city='Riyadh',
                province='Riyadh',
                district='',
                street='',
                building_no='',
                postal_code='',
                map_link='https://maps.example/drop',
                contact_name='',
                mobile_no_1='',
                mobile_no_2='',
                site_instructions='',
            ),
            booking=None,
        )
        block = build_active_shipment_slice(shipment)
        self.assertEqual(block['job_id'], str(shipment_id))
        self.assertEqual(block['route']['route_display'], 'Route A')
        self.assertEqual(block['route']['route_display_start'], 'Route A')
        self.assertEqual(block['route']['route_display_end'], '')
        self.assertEqual(block['pickup_address']['address_id'], str(pickup_id))

    def test_dashboard_payload_includes_active_job(self):
        shipment_id = uuid4()
        shipment = SimpleNamespace(
            pk=shipment_id,
            shipment_id=shipment_id,
            shipment_no='SH-200',
            order_type='',
            booking_item_type='Outbound',
            shipment_status='Loaded',
            trip_type='One-Way',
            route_display='',
            loading_address=None,
            delivery_address=None,
            booking=None,
        )
        context = DriverDashboardContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='u1',
            active_shipment=shipment,
        )
        payload = DashboardResponseBuilder().build(context)
        self.assertIn('active_job', payload)
        self.assertEqual(payload['active_job']['job_id'], str(shipment_id))
        self.assertEqual(payload['active_job']['job_type'], 'shipment')
        self.assertEqual(payload['active_job']['order_type'], 'Credit')
