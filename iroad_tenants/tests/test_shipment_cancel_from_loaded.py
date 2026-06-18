"""Shipment cancel validation helpers."""
from __future__ import annotations

from unittest import TestCase

from iroad_tenants.shipment_cancel import shipment_cancel_guard_errors


class ShipmentCancelGuardLoadedTests(TestCase):
    def test_active_loaded_shipment_can_be_cancelled(self):
        class _Shipment:
            shipment_status = 'Loaded'

        self.assertEqual(shipment_cancel_guard_errors(_Shipment()), [])
