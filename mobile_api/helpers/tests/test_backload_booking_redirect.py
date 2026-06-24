"""Tests for backload booking redirect (closed outbound → booking bootstrap)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.helpers.backload_booking_redirect import (
    pivot_booking_to_active_shipment,
    pivot_context_to_backload_booking,
    should_pivot_booking_to_active_shipment,
    should_pivot_shipment_to_backload_booking,
)


def _booking(*, assigned=1, backload=1, trip_type='Round'):
    return SimpleNamespace(
        pk='bk-1',
        booking_id='bk-1',
        booking_no='BK-0042',
        trip_type=trip_type,
        assigned_driver_id=assigned,
        booking_line_backload_driver_id=backload,
    )


def _shipment(*, line='Outbound', status='Closed'):
    return SimpleNamespace(
        pk='sh-1',
        shipment_id='sh-1',
        shipment_no='SH-0051',
        booking_item_type=line,
        shipment_status=status,
    )


class BackloadBookingRedirectTests(TestCase):
    def test_should_pivot_when_outbound_closed_and_backload_pending(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])

        self.assertTrue(
            should_pivot_shipment_to_backload_booking(
                driver=driver,
                booking=booking,
                shipment=outbound,
            )
        )

    def test_should_pivot_when_outbound_cancelled_and_backload_pending(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Cancelled')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])

        self.assertTrue(
            should_pivot_shipment_to_backload_booking(
                driver=driver,
                booking=booking,
                shipment=outbound,
            )
        )

    def test_should_not_pivot_when_backload_shipment_exists(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed')
        backload = _shipment(line='Backload', status='Planned')
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        self.assertFalse(
            should_pivot_shipment_to_backload_booking(
                driver=driver,
                booking=booking,
                shipment=outbound,
            )
        )

    def test_pivot_mutates_context_to_booking_scope(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])
        ctx = SimpleNamespace(
            job_type='shipment',
            job_id='sh-1',
            shipment=outbound,
            booking=booking,
            resolver_meta={},
        )

        self.assertTrue(
            pivot_context_to_backload_booking(
                driver=driver,
                booking=booking,
                shipment=outbound,
                context=ctx,
            )
        )
        self.assertEqual(ctx.job_type, 'booking')
        self.assertEqual(ctx.job_id, 'bk-1')
        self.assertIsNone(ctx.shipment)
        self.assertTrue(ctx.resolver_meta.get('backload_booking_redirect'))

    def test_should_pivot_booking_to_active_outbound_shipment(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking(trip_type='One-Way')
        outbound = _shipment(status='At Delivery', line='Outbound')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])

        self.assertTrue(
            should_pivot_booking_to_active_shipment(
                driver=driver,
                booking=booking,
            )
        )

    def test_should_not_pivot_booking_during_backload_bootstrap(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])

        self.assertFalse(
            should_pivot_booking_to_active_shipment(
                driver=driver,
                booking=booking,
            )
        )

    def test_pivot_booking_mutates_context_to_active_shipment(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking(trip_type='One-Way')
        outbound = _shipment(status='In Transit', line='Outbound')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])
        ctx = SimpleNamespace(
            job_type='booking',
            job_id='bk-1',
            shipment=None,
            booking=booking,
            resolver_meta={},
        )

        self.assertTrue(
            pivot_booking_to_active_shipment(
                driver=driver,
                booking=booking,
                context=ctx,
            )
        )
        self.assertEqual(ctx.job_type, 'shipment')
        self.assertEqual(ctx.job_id, 'sh-1')
        self.assertIs(ctx.shipment, outbound)
        self.assertTrue(ctx.resolver_meta.get('active_shipment_redirect'))
