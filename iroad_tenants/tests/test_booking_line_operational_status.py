"""Booking line operational status when round-trip legs complete."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from tenant_workspace.models import TenantBooking, TenantShipment

from iroad_tenants.views import _tenant_booking_line_operational_status


def _booking():
    b = SimpleNamespace()
    b.booking_id = uuid4()
    b.booking_status = TenantBooking.Status.CONFIRMED
    return b


def _shipment_qs(*shipments):
    terminal = (
        TenantShipment.ShipmentStatus.CANCELLED,
        TenantShipment.ShipmentStatus.CLOSED,
    )
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
        if kwargs.get('shipment_status') == TenantShipment.ShipmentStatus.CLOSED:
            return closed_qs
        if kwargs.get('shipment_status') == TenantShipment.ShipmentStatus.CANCELLED:
            return cancelled_qs
        return qs

    qs.exclude = exclude
    qs.filter = filter
    return qs


class BookingLineOperationalStatusTests(SimpleTestCase):
    @patch('iroad_tenants.views.TenantShipment.objects')
    def test_closed_outbound_shows_executed_even_if_newer_open_duplicate(self, mock_objects):
        booking = _booking()
        closed = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
        )
        open_dup = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.LOADED,
        )
        mock_objects.filter.return_value = _shipment_qs(closed, open_dup)

        status = _tenant_booking_line_operational_status(booking, 'Outbound')

        self.assertEqual(status, 'In Execution')

    @patch('iroad_tenants.views.TenantShipment.objects')
    def test_only_closed_outbound_shows_executed(self, mock_objects):
        booking = _booking()
        closed = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
        )
        mock_objects.filter.return_value = _shipment_qs(closed)

        status = _tenant_booking_line_operational_status(booking, 'Outbound')

        self.assertEqual(status, 'Executed')

    @patch('iroad_tenants.views.TenantShipment.objects')
    def test_both_legs_closed_booking_lines_executed(self, mock_objects):
        booking = _booking()

        def _filter_side_effect(**kwargs):
            line_type = kwargs.get('booking_item_type')
            if line_type == 'Outbound':
                return _shipment_qs(
                    SimpleNamespace(
                        shipment_status=TenantShipment.ShipmentStatus.CLOSED,
                    ),
                )
            if line_type == 'Backload':
                return _shipment_qs(
                    SimpleNamespace(
                        shipment_status=TenantShipment.ShipmentStatus.CLOSED,
                    ),
                )
            return _shipment_qs()

        mock_objects.filter.side_effect = _filter_side_effect

        self.assertEqual(
            _tenant_booking_line_operational_status(booking, 'Outbound'),
            'Executed',
        )
        self.assertEqual(
            _tenant_booking_line_operational_status(booking, 'Backload'),
            'Executed',
        )
