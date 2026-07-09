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
    @patch('iroad_tenants.shipment_cancel.resolve_cancel_shipment_action')
    @patch('iroad_tenants.shipment_cancel.append_shipment_r1_cancel_action_log')
    def test_cancel_from_closed_allowed(self, mock_log, mock_resolve):
        mock_action = MagicMock()
        mock_action.shipment_status_impact = 'Cancelled'
        mock_resolve.return_value = mock_action
        mock_log.return_value = MagicMock()

        shipment = MagicMock()
        shipment.shipment_status = 'Closed'
        shipment.booking_id = None
        shipment.booking = None
        shipment.truck_id = None
        shipment.driver_id = None
        shipment.sync_collection_status_for_lifecycle = MagicMock()

        ok, errors = apply_shipment_cancel(shipment)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        self.assertEqual(shipment.shipment_status, 'Cancelled')
        mock_log.assert_called_once()

    @patch('iroad_tenants.shipment_cancel.resolve_cancel_shipment_action', return_value=None)
    def test_cancel_blocked_when_operation_action_missing(self, _mock_resolve):
        shipment = MagicMock()
        shipment.shipment_status = 'Loaded'
        ok, errors = apply_shipment_cancel(shipment)
        self.assertFalse(ok)
        self.assertTrue(errors)

    @patch('iroad_tenants.booking_status.sync_booking_status_after_item_change')
    @patch('iroad_tenants.shipment_cancel.resolve_cancel_shipment_action')
    @patch('iroad_tenants.shipment_cancel.append_shipment_r1_cancel_action_log')
    def test_cancel_syncs_booking_status_when_all_legs_cancelled(
        self,
        mock_log,
        mock_resolve,
        mock_sync,
    ):
        mock_action = MagicMock()
        mock_action.shipment_status_impact = 'Cancelled'
        mock_resolve.return_value = mock_action
        mock_log.return_value = MagicMock()

        booking = MagicMock()
        booking.booking_status = 'Confirmed'
        shipment = MagicMock()
        shipment.shipment_status = 'Loaded'
        shipment.booking_id = 'bk-1'
        shipment.booking = booking
        shipment.truck_id = None
        shipment.driver_id = None
        shipment.sync_collection_status_for_lifecycle = MagicMock()

        def _sync(target):
            target.booking_status = 'Cancelled'

        mock_sync.side_effect = _sync

        ok, errors = apply_shipment_cancel(shipment)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        mock_sync.assert_called_once_with(booking)
        booking.save.assert_called_once()
