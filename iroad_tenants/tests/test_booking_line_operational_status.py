"""Booking line operational status when round-trip legs complete."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from iroad_tenants.booking_status import derive_booking_line_status


def _booking():
    b = SimpleNamespace()
    b.booking_id = uuid4()
    b.booking_status = 'Confirmed'
    return b


def _shipment_qs(*shipments):
    terminal = ('Cancelled', 'Closed')
    open_rows = [
        s for s in shipments if getattr(s, 'shipment_status', None) not in terminal
    ]
    closed_rows = [
        s
        for s in shipments
        if getattr(s, 'shipment_status', None) == TenantShipment.ShipmentStatus.CLOSED
    ]
    cancelled_rows = [
        s
        for s in shipments
        if getattr(s, 'shipment_status', None)
        == TenantShipment.ShipmentStatus.CANCELLED
    ]

    qs = MagicMock()
    qs.exists.return_value = bool(shipments)

    open_qs = MagicMock()
    open_qs.exists.return_value = bool(open_rows)

    closed_qs = MagicMock()
    closed_qs.exists.return_value = bool(closed_rows)

    cancelled_qs = MagicMock()
    cancelled_qs.exists.return_value = bool(cancelled_rows)

    def exclude(**kwargs):
        status_in = kwargs.get('shipment_status__in') or ()
        if set(status_in) == set(terminal):
            return open_qs
        return qs

    def filter(**kwargs):
        if kwargs.get('shipment_status') == 'Closed':
            return closed_qs
        if kwargs.get('shipment_status') == 'Cancelled':
            return cancelled_qs
        return qs

    qs.exclude = exclude
    qs.filter = filter
    return qs


class BookingLineOperationalStatusTests(TestCase):
    @patch('tenant_workspace.models.TenantShipment.objects')
    def test_closed_outbound_shows_executed_even_if_newer_open_duplicate(self, mock_objects):
        booking = _booking()
        closed = SimpleNamespace(
            shipment_status='Closed',
        )
        open_dup = SimpleNamespace(
            shipment_status='Loaded',
        )
        mock_objects.filter.return_value = _shipment_qs(closed, open_dup)

        status = derive_booking_line_status(booking, 'Outbound')

        self.assertEqual(status, 'In Progress')

    @patch('tenant_workspace.models.TenantShipment.objects')
    def test_only_closed_outbound_shows_executed(self, mock_objects):
        booking = _booking()
        closed = SimpleNamespace(
            shipment_status='Closed',
        )
        mock_objects.filter.return_value = _shipment_qs(closed)

        status = derive_booking_line_status(booking, 'Outbound')

        self.assertEqual(status, 'Completed')

    @patch('tenant_workspace.models.TenantShipment.objects')
    def test_both_legs_closed_booking_lines_executed(self, mock_objects):
        booking = _booking()

        def _filter_side_effect(**kwargs):
            line_type = kwargs.get('booking_item_type')
            if line_type == 'Outbound':
                return _shipment_qs(
                    SimpleNamespace(
                        shipment_status='Closed',
                    ),
                )
            if line_type == 'Backload':
                return _shipment_qs(
                    SimpleNamespace(
                        shipment_status='Closed',
                    ),
                )
            return _shipment_qs()

        mock_objects.filter.side_effect = _filter_side_effect

        self.assertEqual(
            derive_booking_line_status(booking, 'Outbound'),
            'Completed',
        )
        self.assertEqual(
            derive_booking_line_status(booking, 'Backload'),
            'Completed',
        )
