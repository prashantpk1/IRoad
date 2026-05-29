"""Tests for route + address location projection."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.job_detail.projections.job_location_projection import (
    _split_combined_route_label,
    serialize_route,
)


class JobLocationProjectionTests(SimpleTestCase):
    def test_split_combined_route_label_em_dash(self):
        start, end = _split_combined_route_label('delhi — Goa')
        self.assertEqual(start, 'delhi')
        self.assertEqual(end, 'Goa')

    def test_split_combined_route_label_arrow(self):
        start, end = _split_combined_route_label('Jeddah → Riyadh')
        self.assertEqual(start, 'Jeddah')
        self.assertEqual(end, 'Riyadh')

    def test_serialize_route_from_origin_destination_fk(self):
        route_id = uuid4()
        booking = SimpleNamespace(
            route_direction='forward',
            route_display='',
            route=SimpleNamespace(
                route_id=route_id,
                route_code='RT-AAAB',
                route_label='delhi — Goa',
                route_type='Domestic',
                origin_point=SimpleNamespace(
                    display_label='Delhi',
                    location_name_english='Delhi',
                    location_name_arabic='',
                ),
                destination_point=SimpleNamespace(
                    display_label='Goa',
                    location_name_english='Goa',
                    location_name_arabic='',
                ),
            ),
        )
        block = serialize_route(booking=booking)
        self.assertEqual(block['route_display_start'], 'Delhi')
        self.assertEqual(block['route_display_end'], 'Goa')
        self.assertEqual(block['route_display'], 'Delhi → Goa')
        self.assertEqual(block['route_code'], 'RT-AAAB')

    def test_serialize_route_splits_denormalized_display_when_no_fk_points(self):
        shipment = SimpleNamespace(route_display='delhi — Goa')
        booking = SimpleNamespace(
            route_direction='forward',
            route_display='',
            route=None,
        )
        block = serialize_route(shipment=shipment, booking=booking)
        self.assertEqual(block['route_display_start'], 'delhi')
        self.assertEqual(block['route_display_end'], 'Goa')
        self.assertEqual(block['route_display'], 'delhi — Goa')
