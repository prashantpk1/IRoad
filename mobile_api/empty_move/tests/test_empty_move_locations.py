"""Tests for empty move location list API."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.empty_move.services.empty_move_locations_service import (
    EmptyMoveLocationsService,
)


class EmptyMoveLocationsServiceTests(SimpleTestCase):
    @patch('mobile_api.empty_move.services.empty_move_locations_service.schema_context')
    @patch(
        'mobile_api.empty_move.services.empty_move_locations_service.TenantLocationMaster'
    )
    def test_list_locations_serializes_active_rows(self, mock_model, _schema):
        loc_id = uuid4()
        row = SimpleNamespace(
            location_id=loc_id,
            pk=loc_id,
            location_code='LC-001',
            location_name_english='Jeddah',
            location_name_arabic='Jeddah',
            display_label='Jeddah',
            province='Makkah',
        )
        qs = MagicMock()
        qs.order_by.return_value = qs
        qs.__getitem__.return_value = [row]
        mock_model.active_serviceable_objects.select_related.return_value = qs

        service = EmptyMoveLocationsService()
        result = service.list_locations(tenant_schema='tenant_test')

        self.assertEqual(len(result['locations']), 1)
        self.assertEqual(result['locations'][0]['location_id'], str(loc_id))
        self.assertEqual(result['locations'][0]['label'], 'Jeddah')

    def test_empty_schema_returns_empty_list(self):
        service = EmptyMoveLocationsService()
        self.assertEqual(
            service.list_locations(tenant_schema='')['locations'],
            [],
        )
