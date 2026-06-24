"""Inbound / backload shipment jobs must swap booking endpoint addresses."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.job_detail.projections.job_location_projection import (
    build_shipment_location_block,
)


class ShipmentInboundAddressSwapTests(SimpleTestCase):
    def test_inbound_shipment_swaps_jeddah_riyadh_without_route_fk(self):
        """
        Route text may come from shipment.route_display; site addresses must still
        swap from booking loading/delivery masters on leg 2.
        """
        booking = SimpleNamespace(
            trip_type='Round',
            route=None,
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
            shipments=SimpleNamespace(all=lambda: []),
        )
        shipment = SimpleNamespace(
            booking_item_type='Inbound',
            route_display='Makkah → jeddah',
            loading_address=booking.loading_address,
            delivery_address=booking.delivery_address,
            booking=booking,
        )
        block = build_shipment_location_block(shipment, booking=booking)
        self.assertEqual(block['pickup_address']['city'], 'Riyadh')
        self.assertEqual(block['drop_address']['city'], 'Jeddah')
        self.assertEqual(
            block['pickup_address']['address_line_2'],
            'Riyadh Address line 2',
        )
        self.assertEqual(
            block['drop_address']['address_line_2'],
            'Jeddahv Address line 2',
        )

    def test_inbound_shipment_ignores_outbound_copied_shipment_fks(self):
        """Shipment row FKs often mirror outbound — leg swap must use booking masters."""
        booking = SimpleNamespace(
            trip_type='Round',
            route=SimpleNamespace(
                route_id=uuid4(),
                route_code='RT-JM',
                route_label='jeddah — Makkah',
                route_type='Domestic',
                origin_point=SimpleNamespace(
                    display_label='jeddah',
                    location_name_english='jeddah',
                    location_name_arabic='',
                ),
                destination_point=SimpleNamespace(
                    display_label='Makkah',
                    location_name_english='Makkah',
                    location_name_arabic='',
                ),
            ),
            loading_address=SimpleNamespace(
                address_id=uuid4(),
                display_name='Jeddah',
                english_label='Jeddah',
                arabic_label='',
                city='Jeddah',
            ),
            delivery_address=SimpleNamespace(
                address_id=uuid4(),
                display_name='Riyadh',
                english_label='Riyadh',
                arabic_label='',
                city='Riyadh',
            ),
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                    ),
                    SimpleNamespace(
                        shipment_status='Created',
                        booking_item_type='Inbound',
                    ),
                ],
            ),
        )
        shipment = SimpleNamespace(
            booking_item_type='Inbound',
            route_display='Makkah → jeddah',
            loading_address=booking.loading_address,
            delivery_address=booking.delivery_address,
            booking=booking,
        )
        block = build_shipment_location_block(shipment, booking=booking)
        self.assertEqual(block['route']['route_display_start'], 'Makkah')
        self.assertEqual(block['pickup_address']['city'], 'Riyadh')
        self.assertEqual(block['drop_address']['city'], 'Jeddah')
