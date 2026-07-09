"""Fleet operational eligibility (PCS §6.2.1)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from iroad_tenants.fleet_operational_eligibility import (
    _driver_include_primary_keys,
    _truck_include_primary_keys,
    booking_eligible_trucks_queryset,
)
from iroad_tenants.fleet_operational_rules import (
    driver_is_available_for_operations,
    driver_operational_block_reason,
    truck_is_available_for_operations,
    truck_operational_block_reason,
)


class TruckOperationalEligibilityTests(TestCase):
    def test_active_available_truck_is_eligible(self):
        truck = SimpleNamespace(status='Active', operational_status='Available')
        self.assertTrue(truck_is_available_for_operations(truck))

    def test_blank_operational_status_treated_as_available(self):
        truck = SimpleNamespace(status='Active', operational_status='')
        self.assertTrue(truck_is_available_for_operations(truck))

    def test_loaded_truck_blocked(self):
        truck = SimpleNamespace(status='Active', operational_status='Loaded')
        self.assertFalse(truck_is_available_for_operations(truck))
        self.assertIn('Loaded', truck_operational_block_reason(truck))

    def test_inactive_truck_blocked(self):
        truck = SimpleNamespace(status='Inactive', operational_status='Available')
        self.assertFalse(truck_is_available_for_operations(truck))
        self.assertIn('Active', truck_operational_block_reason(truck))


class DriverOperationalEligibilityTests(TestCase):
    def test_active_driver_is_eligible(self):
        driver = SimpleNamespace(driver_status='Active')
        self.assertTrue(driver_is_available_for_operations(driver))

    def test_inactive_driver_blocked(self):
        driver = SimpleNamespace(driver_status='Inactive')
        self.assertFalse(driver_is_available_for_operations(driver))
        self.assertIn('Active', driver_operational_block_reason(driver))


class IncludePrimaryKeyNormalizationTests(TestCase):
    def test_truck_include_primary_keys_accepts_uuid_strings(self):
        truck_id = uuid.uuid4()
        self.assertEqual(
            _truck_include_primary_keys([str(truck_id)]),
            [truck_id],
        )

    def test_truck_include_primary_keys_ignores_display_codes_without_lookup(self):
        with patch('iroad_tenants.fleet_operational_eligibility.TruckMaster') as truck_model:
            truck_model.objects.filter.return_value.values_list.return_value = []
            self.assertEqual(
                _truck_include_primary_keys(['TR-0003']),
                [],
            )
            truck_model.objects.filter.assert_called_once_with(truck_code__in=['TR-0003'])

    def test_truck_include_primary_keys_resolves_truck_code_to_uuid(self):
        truck_id = uuid.uuid4()
        with patch('iroad_tenants.fleet_operational_eligibility.TruckMaster') as truck_model:
            truck_model.objects.filter.return_value.values_list.return_value = [truck_id]
            self.assertEqual(
                _truck_include_primary_keys(['TR-0003']),
                [truck_id],
            )

    def test_driver_include_primary_keys_ignores_display_labels(self):
        self.assertEqual(
            _driver_include_primary_keys(['DR-0001 - John Doe']),
            [],
        )

    def test_booking_eligible_trucks_queryset_does_not_raise_for_truck_code(self):
        with patch('iroad_tenants.fleet_operational_eligibility.TruckMaster') as truck_model:
            active_qs = MagicMock()
            active_qs.filter.return_value = active_qs
            active_qs.values.return_value = []
            truck_model.active_objects = active_qs
            truck_model.OperationalStatus.AVAILABLE = 'Available'
            truck_model.objects.filter.return_value.distinct.return_value.select_related.return_value.order_by.return_value = []

            booking_eligible_trucks_queryset(include_truck_ids=['TR-0003'])

            truck_model.objects.filter.assert_called()
