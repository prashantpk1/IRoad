"""Tests for job header route and address projection."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.job_header_projection import build_job_header


class JobHeaderProjectionTests(SimpleTestCase):
    def test_shipment_includes_route_and_addresses(self):
        pickup_id = uuid4()
        drop_id = uuid4()
        route_id = uuid4()
        shipment = SimpleNamespace(
            shipment_no='SH-100',
            order_type='COD',
            route_display='Jeddah → Riyadh',
            loading_address=SimpleNamespace(
                address_id=pickup_id,
                address_code='ADDR-P1',
                display_name='Pickup Site',
                english_label='Pickup EN',
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
                contact_name='Ali',
                mobile_no_1='+966500000001',
                mobile_no_2='',
                site_instructions='Gate 2',
            ),
            delivery_address=SimpleNamespace(
                address_id=drop_id,
                address_code='ADDR-D1',
                display_name='Drop Site',
                english_label='Drop EN',
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
                contact_name='Sara',
                mobile_no_1='+966500000002',
                mobile_no_2='',
                site_instructions='',
            ),
            booking=None,
        )
        booking = SimpleNamespace(
            execution_date=None,
            booking_date=None,
            client_account=SimpleNamespace(
                display_name='Test Client',
                name_english='Test Client',
                name_arabic='',
            ),
            route_display='',
            route_direction='forward',
            route=SimpleNamespace(
                route_id=route_id,
                route_code='RT-01',
                route_label='Jeddah — Riyadh',
                route_type='Domestic',
                origin_point=SimpleNamespace(
                    display_label='Jeddah',
                    location_name_english='Jeddah',
                    location_name_arabic='',
                ),
                destination_point=SimpleNamespace(
                    display_label='Riyadh',
                    location_name_english='Riyadh',
                    location_name_arabic='',
                ),
            ),
            loading_address=None,
            delivery_address=None,
        )
        context = JobDetailContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id=str(uuid4()),
            shipment=shipment,
            booking=booking,
        )
        header = build_job_header(context)
        self.assertEqual(header['job_no'], 'SH-100')
        self.assertEqual(header['order_type'], 'COD')
        self.assertEqual(header['client_name'], 'Test Client')
        self.assertEqual(header['execution_date'], '')
        self.assertEqual(header['route']['route_display'], 'Jeddah → Riyadh')
        self.assertEqual(header['route']['route_display_start'], 'Jeddah')
        self.assertEqual(header['route']['route_display_end'], 'Riyadh')
        self.assertEqual(header['route']['route_code'], 'RT-01')
        self.assertEqual(header['pickup_address']['address_id'], str(pickup_id))
        self.assertEqual(header['pickup_address']['map_link'], 'https://maps.example/pickup')
        self.assertEqual(header['drop_address']['address_id'], str(drop_id))
        self.assertEqual(header['drop_address']['city'], 'Riyadh')
