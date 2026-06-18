"""Shipment cancel rules (PCS §4.2)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from iroad_tenants.shipment_cancel import (
    apply_shipment_cancel,
    shipment_cancel_guard_errors,
)


class ShipmentCancelGuardTests(TestCase):
    def test_blocks_already_cancelled(self):
        shipment = SimpleNamespace(shipment_status='Cancelled')
        self.assertEqual(
            shipment_cancel_guard_errors(shipment),
            ['Shipment is already cancelled.'],
        )

    def test_allows_active_shipment(self):
        shipment = SimpleNamespace(shipment_status='Loaded')
        self.assertEqual(shipment_cancel_guard_errors(shipment), [])


class ShipmentCancelApplyTests(TestCase):
    @patch('iroad_tenants.shipment_cancel.append_shipment_r1_cancel_action_log')
    def test_cancel_from_closed_allowed(self, mock_log):
        shipment = MagicMock()
        shipment.shipment_status = 'Closed'
        shipment.booking_id = None
        shipment.truck_id = None
        shipment.driver_id = None
        shipment.sync_collection_status_for_lifecycle = MagicMock()

        ok, errors = apply_shipment_cancel(shipment)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertEqual(shipment.shipment_status, 'Cancelled')
        mock_log.assert_called_once()
