"""Unit tests for empty move geocode arrival view."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory

from mobile_api.empty_move.views.empty_move_geocode_arrival_view import (
    EmptyMoveGeocodeArrivalAPIView,
    reverse_geocode,
)


class EmptyMoveGeocodeArrivalTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = EmptyMoveGeocodeArrivalAPIView.as_view(permission_classes=[], throttle_classes=[])
        self.job_id = uuid4()
        self.url = reverse('mobile_api:driver_empty_move_geocode_arrival', kwargs={'job_id': self.job_id})

    @patch('django.conf.settings.GOOGLE_MAPS_API_KEY', '')
    def test_reverse_geocode_fallback_Jeddah(self):
        address = reverse_geocode(21.5433, 39.1728)
        self.assertEqual(address, "King Abdulaziz Rd, Jeddah, Saudi Arabia")

    @patch('django.conf.settings.GOOGLE_MAPS_API_KEY', '')
    def test_reverse_geocode_fallback_Makkah(self):
        address = reverse_geocode(21.3891, 39.8579)
        self.assertEqual(address, "Industrial Area, Makkah, Saudi Arabia")

    @patch('django.conf.settings.GOOGLE_MAPS_API_KEY', '')
    def test_reverse_geocode_fallback_generic(self):
        address = reverse_geocode(10.0, 20.0)
        self.assertEqual(address, "Geocoded Location (10.0, 20.0)")

    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.tenant_schema_for_request', return_value='tenant_test')
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.resolve_mobile_driver_session')
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.get_mobile_jwt_payload', return_value={})
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.TenantTruckMovementLog')
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.reverse_geocode', return_value="Industrial Area, Makkah, Saudi Arabia")
    def test_view_resolves_geocode_and_updates_db(self, mock_reverse, mock_movement_model, _jwt, mock_resolve_session, _schema):
        driver_id = uuid4()
        driver = SimpleNamespace(pk=driver_id, driver_id=driver_id)
        mock_resolve_session.return_value = (SimpleNamespace(pk=uuid4()), driver, None, None)

        movement = MagicMock()
        movement.driver_id = driver_id
        mock_movement_model.objects.get.return_value = movement

        request = self.factory.post(self.url, {'latitude': 21.3891, 'longitude': 39.8579}, format='json')
        response = self.view(request, job_id=self.job_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 1)
        
        addr_data = response.data['data']['delivery_address']
        self.assertEqual(addr_data['to_address'], "Industrial Area, Makkah, Saudi Arabia")
        self.assertEqual(addr_data['latitude'], "21.3891")
        self.assertEqual(addr_data['longitude'], "39.8579")
        self.assertEqual(addr_data['location_capture_mode'], "gps")
        self.assertTrue(addr_data['gps_capture_required'])

        movement.save.assert_called_once()
        self.assertEqual(movement.to_location_address, "Industrial Area, Makkah, Saudi Arabia")
        self.assertEqual(movement.to_latitude, "21.3891")
        self.assertEqual(movement.to_longitude, "39.8579")

    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.tenant_schema_for_request', return_value='tenant_test')
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.resolve_mobile_driver_session')
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.get_mobile_jwt_payload', return_value={})
    @patch('mobile_api.empty_move.views.empty_move_geocode_arrival_view.TenantTruckMovementLog')
    def test_view_blocks_unowned_job(self, mock_movement_model, _jwt, mock_resolve_session, _schema):
        driver_id = uuid4()
        driver = SimpleNamespace(pk=driver_id, driver_id=driver_id)
        mock_resolve_session.return_value = (SimpleNamespace(pk=uuid4()), driver, None, None)

        movement = MagicMock()
        movement.driver_id = uuid4()  # different driver
        mock_movement_model.objects.get.return_value = movement

        request = self.factory.post(self.url, {'latitude': 21.3891, 'longitude': 39.8579}, format='json')
        response = self.view(request, job_id=self.job_id)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['status'], 0)
        self.assertEqual(response.data['data']['error_code'], "forbidden")
