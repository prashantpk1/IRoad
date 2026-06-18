"""Fleet operational eligibility (PCS §6.2.1)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

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
