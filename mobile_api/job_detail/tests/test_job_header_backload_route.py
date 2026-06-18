"""Tests for job header backload route on booking jobs."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.job_header_projection import build_job_header


def _location(name: str):
    return SimpleNamespace(
        display_label=name,
        location_name_english=name,
        location_name_arabic='',
    )


class JobHeaderBackloadRouteTests(SimpleTestCase):
    def test_booking_backload_bootstrap_shows_return_route_and_swapped_addresses(self):
        route_id = uuid4()
        jeddah = _location('Jeddah')
        makkah = _location('Makkah')
        booking = SimpleNamespace(
            booking_no='BK-0042',
            trip_type='Round',
            order_type='Credit',
            booking_status='Confirmed',
            execution_date=None,
            booking_date=None,
            route_direction='forward',
            route_display='Jeddah → Makkah',
            route=SimpleNamespace(
                route_id=route_id,
                route_code='RT-JM',
                route_label='Jeddah — Makkah',
                route_type='Domestic',
                origin_point=jeddah,
                destination_point=makkah,
            ),
            loading_address=SimpleNamespace(
                address_id=uuid4(),
                address_code='LD-J',
                display_name='Industrial City Phase 1, Jeddah',
                english_label='Industrial City Phase 1, Jeddah',
                arabic_label='',
                address_category='Loading',
                address_line_1='',
                address_line_2='Jeddah Address line 2',
                city='Jeddah',
                province='',
                district='',
                street='',
                building_no='',
                postal_code='',
                map_link='',
                contact_name='',
                mobile_no_1='',
                mobile_no_2='',
                site_instructions='',
            ),
            delivery_address=SimpleNamespace(
                address_id=uuid4(),
                address_code='DL-M',
                display_name='Zamzam Distribution Center, Mecca',
                english_label='Zamzam Distribution Center, Mecca',
                arabic_label='',
                address_category='Delivery',
                address_line_1='',
                address_line_2='Makkah Address line 2',
                city='Mecca',
                province='',
                district='',
                street='',
                building_no='',
                postal_code='',
                map_link='',
                contact_name='',
                mobile_no_1='',
                mobile_no_2='',
                site_instructions='',
            ),
            client_account=SimpleNamespace(
                display_name='UATC',
                name_english='UATC',
                name_arabic='',
            ),
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        pk=uuid4(),
                        shipment_id=uuid4(),
                        shipment_no='SH-0051',
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                        shipment_sequence=1,
                    ),
                ],
            ),
        )
        context = JobDetailContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='booking',
            job_id=str(uuid4()),
            booking=booking,
        )
        header = build_job_header(context)
        self.assertEqual(header['route']['route_display_start'], 'Makkah')
        self.assertEqual(header['route']['route_display_end'], 'Jeddah')
        self.assertEqual(header['route']['route_direction'], 'reverse')
        self.assertEqual(
            header['pickup_address']['label'],
            'Zamzam Distribution Center, Mecca',
        )
        self.assertEqual(
            header['drop_address']['label'],
            'Industrial City Phase 1, Jeddah',
        )
        self.assertEqual(
            header['booking_execution_stage'],
            policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
        )
    def test_booking_backload_swaps_jeddah_riyadh_when_outbound_closed(self):
        """User data: loading=Jeddah, delivery=Riyadh — backload must swap endpoints."""
        route_id = uuid4()
        jeddah = _location('Jeddah')
        makkah = _location('Makkah')
        booking = SimpleNamespace(
            booking_no='BK-0042',
            trip_type='Round',
            order_type='Credit',
            booking_status='Confirmed',
            execution_date=None,
            booking_date=None,
            route_direction='forward',
            route_display='jeddah To Makkah',
            route=SimpleNamespace(
                route_id=route_id,
                route_code='RT-JM',
                route_label='jeddah — Makkah',
                route_type='Domestic',
                origin_point=jeddah,
                destination_point=makkah,
            ),
            loading_address=SimpleNamespace(
                address_id=uuid4(),
                display_name='Jeddah',
                english_label='Jeddah',
                arabic_label='',
                address_line_2='Jeddahv Address line 2',
                city='Jeddah',
            ),
            delivery_address=SimpleNamespace(
                address_id=uuid4(),
                display_name='Riyadh',
                english_label='Riyadh',
                arabic_label='',
                address_line_2='Riyadh Address line 2',
                city='Riyadh',
            ),
            client_account=SimpleNamespace(
                display_name='UATC',
                name_english='UATC',
                name_arabic='',
            ),
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        pk=uuid4(),
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                        shipment_sequence=1,
                    ),
                ],
            ),
        )
        context = JobDetailContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='booking',
            job_id=str(uuid4()),
            booking=booking,
        )
        header = build_job_header(context)
        self.assertEqual(header['pickup_address']['city'], 'Riyadh')
        self.assertEqual(header['drop_address']['city'], 'Jeddah')
        self.assertEqual(header['booking_item_type'], 'Backload')

