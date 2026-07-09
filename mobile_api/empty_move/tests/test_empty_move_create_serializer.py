"""Tests for empty move create request validation."""
from __future__ import annotations

from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.empty_move.serializers.empty_move_create_serializer import (
    EmptyMoveCreateRequestSerializer,
)


class EmptyMoveCreateRequestSerializerTests(SimpleTestCase):
    def test_accepts_reason_and_start_gps_only(self):
        serializer = EmptyMoveCreateRequestSerializer(
            data={
                'empty_move_reason': 'reposition',
                'latitude': 21.5433,
                'longitude': 39.1728,
                'from_address': 'King Abdulaziz Rd, Jeddah',
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['from_latitude'], 21.5433)

    def test_accepts_legacy_manual_places_payload(self):
        serializer = EmptyMoveCreateRequestSerializer(
            data={
                'empty_move_reason': 'reposition',
                'from_address': 'King Abdulaziz Rd, Jeddah',
                'from_latitude': 21.5433,
                'from_longitude': 39.1728,
                'to_address': 'Industrial Area, Makkah',
                'to_latitude': 21.4225,
                'to_longitude': 39.8262,
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_accepts_location_master_with_places_snapshot(self):
        serializer = EmptyMoveCreateRequestSerializer(
            data={
                'empty_move_reason': 'maintenance',
                'from_location_id': str(uuid4()),
                'to_location_id': str(uuid4()),
                'from_address': 'Depot A',
                'from_latitude': 24.7136,
                'from_longitude': 46.6753,
                'to_address': 'Depot B',
                'to_latitude': 21.4858,
                'to_longitude': 39.1925,
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_missing_start_gps(self):
        serializer = EmptyMoveCreateRequestSerializer(
            data={
                'empty_move_reason': 'reposition',
            },
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('latitude', serializer.errors)

    def test_accepts_from_coords_without_to_on_gps_mode(self):
        serializer = EmptyMoveCreateRequestSerializer(
            data={
                'empty_move_reason': 'reposition',
                'from_address': 'Only from address',
                'from_latitude': 21.5433,
                'from_longitude': 39.1728,
            },
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_same_coordinates_on_legacy_manual_route(self):
        serializer = EmptyMoveCreateRequestSerializer(
            data={
                'empty_move_reason': 'reposition',
                'from_address': 'Point A',
                'from_latitude': 21.5433,
                'from_longitude': 39.1728,
                'to_address': 'Point B',
                'to_latitude': 21.5433,
                'to_longitude': 39.1728,
            },
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('to_address', serializer.errors)
