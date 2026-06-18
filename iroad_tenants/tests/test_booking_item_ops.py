"""Booking item delete/cancel rules (PCS §3.7)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from iroad_tenants.booking_item_ops import (
    DB_TRIP_ONE_WAY,
    DB_TRIP_ROUND,
    LINE_BACKLOAD,
    LINE_OUTBOUND,
    apply_booking_item_cancel,
    apply_booking_item_delete,
    booking_line_action_flags,
)


def _round_booking():
    booking = SimpleNamespace()
    booking.booking_id = uuid4()
    booking.booking_status = 'Confirmed'
    booking.trip_type = DB_TRIP_ROUND
    booking.route_direction = 'forward'
    booking.route_display = 'Jeddah To Yanbu'
    booking.route = None
    booking.assigned_truck = None
    booking.assigned_driver = None
    booking.booking_line_cod_amount = 100
    booking.booking_line_pod_doc_count = 1
    booking.booking_line_backload_truck = SimpleNamespace(pk='truck-2')
    booking.booking_line_backload_driver = SimpleNamespace(pk='driver-2')
    booking.booking_line_backload_cod_amount = 50
    booking.booking_line_backload_pod_doc_count = 2
    booking.loading_booking_item = LINE_OUTBOUND
    booking.delivery_booking_item = LINE_OUTBOUND
    booking.cargo_booking_item = LINE_OUTBOUND
    booking.save = MagicMock()
    return booking


class BookingLineActionFlagTests(TestCase):
    @patch('iroad_tenants.booking_item_ops._line_shipments')
    def test_delete_allowed_without_shipment(self, mock_line_shipments):
        mock_line_shipments.return_value = []
        booking = _round_booking()
        flags = booking_line_action_flags(booking, LINE_BACKLOAD)
        self.assertTrue(flags['can_delete'])
        self.assertFalse(flags['can_cancel'])

    @patch('iroad_tenants.booking_item_ops._line_shipments')
    def test_cancel_allowed_when_only_cancelled_shipments(self, mock_line_shipments):
        mock_line_shipments.return_value = [
            SimpleNamespace(shipment_status='Cancelled'),
        ]
        booking = _round_booking()
        flags = booking_line_action_flags(booking, LINE_OUTBOUND)
        self.assertFalse(flags['can_delete'])
        self.assertTrue(flags['can_cancel'])

    @patch('iroad_tenants.booking_item_ops._line_shipments')
    def test_no_action_when_active_shipment_exists(self, mock_line_shipments):
        mock_line_shipments.return_value = [
            SimpleNamespace(shipment_status='Loaded'),
        ]
        booking = _round_booking()
        flags = booking_line_action_flags(booking, LINE_OUTBOUND)
        self.assertFalse(flags['can_delete'])
        self.assertFalse(flags['can_cancel'])


class BookingItemDeleteTests(TestCase):
    @patch('iroad_tenants.booking_item_ops.sync_booking_status_after_item_change')
    @patch('iroad_tenants.booking_item_ops.booking_line_action_flags')
    def test_delete_backload_sets_one_way(self, mock_flags, mock_sync):
        mock_flags.return_value = {'can_delete': True, 'can_cancel': False}
        booking = _round_booking()
        errors = apply_booking_item_delete(booking, LINE_BACKLOAD)
        self.assertEqual(errors, [])
        self.assertEqual(booking.trip_type, DB_TRIP_ONE_WAY)
        self.assertIsNone(booking.booking_line_backload_truck)
        booking.save.assert_called_once()
        mock_sync.assert_called_once_with(booking)

    @patch('iroad_tenants.booking_item_ops.sync_booking_status_after_item_change')
    @patch('iroad_tenants.booking_item_ops.booking_line_action_flags')
    def test_delete_outbound_promotes_backload_and_reverses_route(self, mock_flags, mock_sync):
        mock_flags.return_value = {'can_delete': True, 'can_cancel': False}
        booking = _round_booking()
        route = SimpleNamespace(
            origin_point=SimpleNamespace(display_label='Jeddah'),
            destination_point=SimpleNamespace(display_label='Yanbu'),
        )
        booking.route = route
        errors = apply_booking_item_delete(booking, LINE_OUTBOUND)
        self.assertEqual(errors, [])
        self.assertEqual(booking.trip_type, DB_TRIP_ONE_WAY)
        self.assertEqual(booking.route_direction, 'reverse')
        self.assertEqual(booking.assigned_truck, SimpleNamespace(pk='truck-2'))


class BookingItemStatusSyncTests(TestCase):
    @patch('iroad_tenants.booking_item_ops.sync_booking_status_after_item_change')
    @patch('iroad_tenants.booking_item_ops.booking_line_action_flags')
    def test_delete_backload_syncs_booking_status(self, mock_flags, mock_sync):
        mock_flags.return_value = {'can_delete': True, 'can_cancel': False}
        booking = _round_booking()
        apply_booking_item_delete(booking, LINE_BACKLOAD)
        mock_sync.assert_called_once_with(booking)

    @patch('iroad_tenants.booking_item_ops.sync_booking_status_after_item_change')
    @patch('iroad_tenants.booking_item_ops.booking_line_action_flags')
    def test_cancel_outbound_syncs_booking_status(self, mock_flags, mock_sync):
        mock_flags.return_value = {'can_delete': False, 'can_cancel': True}
        booking = _round_booking()
        apply_booking_item_cancel(booking, LINE_OUTBOUND)
        mock_sync.assert_called_once_with(booking)
