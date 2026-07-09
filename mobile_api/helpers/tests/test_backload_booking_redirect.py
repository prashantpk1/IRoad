"""Tests for backload booking redirect (closed outbound → booking bootstrap)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from mobile_api.helpers.backload_booking_redirect import (
    pivot_booking_to_active_shipment,
    pivot_closed_shipment_to_active_leg,
    pivot_context_to_backload_booking,
    should_pivot_booking_to_active_shipment,
    should_pivot_closed_shipment_to_active_leg,
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
    def test_should_not_pivot_when_outbound_delivered_awaiting_job_close(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Delivered')
        outbound.pod_status = 'Completed'
        outbound.collection_status = 'Collected'
        booking.shipments = SimpleNamespace(all=lambda: [outbound])

        with patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_shipment_business_complete',
            return_value=False,
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_shipment_execution_complete',
            return_value=True,
        ):
            self.assertFalse(
                should_pivot_shipment_to_backload_booking(
                    driver=driver,
                    booking=booking,
                    shipment=outbound,
                )
            )

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

    def test_should_pivot_when_outbound_complete_empty_line_type(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='')
        booking.shipments = SimpleNamespace(all=lambda: [outbound])

        self.assertTrue(
            should_pivot_shipment_to_backload_booking(
                driver=driver,
                booking=booking,
                shipment=outbound,
            )
        )

    def test_should_pivot_when_backload_created_needs_preshipment(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        backload = _shipment(line='Backload', status='Created')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'iroad_tenants.operation_execution._shipment_has_active_movement',
            return_value=False,
        ):
            self.assertTrue(
                should_pivot_shipment_to_backload_booking(
                    driver=driver,
                    booking=booking,
                    shipment=outbound,
                )
            )

    def test_coerce_active_leg_replaces_completed_outbound(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        outbound.booking = booking
        backload = _shipment(line='Backload', status='At Delivery')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'mobile_api.helpers.backload_booking_redirect.policy.get_active_shipment_for_driver',
            return_value=backload,
        ):
            from mobile_api.helpers.backload_booking_redirect import (
                coerce_driver_active_shipment_leg,
            )

            self.assertIs(
                coerce_driver_active_shipment_leg(driver, outbound),
                backload,
            )

    def test_coerce_active_backload_without_outbound_execution_complete(self):
        """Round-2 Hard POD may still send round-1 shipment id while backload is active."""
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='POD Submitted', line='Outbound')
        outbound.booking = booking
        backload = _shipment(line='Backload', status='POD Submitted')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_shipment_execution_complete',
            return_value=False,
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.get_active_shipment_for_driver',
            return_value=backload,
        ):
            from mobile_api.helpers.backload_booking_redirect import (
                coerce_driver_active_shipment_leg,
            )

            self.assertIs(
                coerce_driver_active_shipment_leg(driver, outbound),
                backload,
            )

    def test_coerce_prefers_open_backload_when_outbound_pod_submitted(self):
        """Leg-2 Hard POD must not validate against round-1 POD Submitted outbound."""
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='POD Submitted', line='Outbound')
        outbound.booking = booking
        backload = _shipment(line='Backload', status='POD Submitted')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'mobile_api.helpers.backload_booking_redirect._load_booking_shipments',
            return_value=[outbound, backload],
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.get_active_shipment_for_driver',
            return_value=outbound,
        ):
            from mobile_api.helpers.backload_booking_redirect import (
                coerce_driver_active_shipment_leg,
            )

            self.assertIs(
                coerce_driver_active_shipment_leg(driver, outbound),
                backload,
            )

    def test_should_not_pivot_closed_to_created_backload_without_movement(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        backload = _shipment(line='Backload', status='Created')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_shipment_execution_complete',
            side_effect=lambda s: str(getattr(s, 'shipment_status', '')).casefold() == 'closed',
        ), patch(
            'iroad_tenants.operation_execution._shipment_has_active_movement',
            return_value=False,
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.get_active_shipment_for_driver',
            return_value=backload,
        ):
            self.assertFalse(
                should_pivot_closed_shipment_to_active_leg(
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

    def test_should_not_pivot_booking_when_backload_row_needs_preshipment(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        backload = _shipment(status='Created', line='Backload')
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'iroad_tenants.operation_execution._shipment_has_active_movement',
            return_value=False,
        ):
            self.assertFalse(
                should_pivot_booking_to_active_shipment(
                    driver=driver,
                    booking=booking,
                )
            )

    def test_should_pivot_booking_when_backload_row_exists_but_outbound_still_active(self):
        """Outbound hard POD must not lose shipment scope when backload row is Created."""
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='At Delivery', line='Outbound')
        backload = _shipment(status='Created', line='Backload')
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'iroad_tenants.operation_execution._shipment_has_active_movement',
            return_value=False,
        ):
            self.assertTrue(
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

    def test_should_pivot_closed_outbound_to_active_backload_shipment(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        backload = _shipment(line='Backload', status='Planned')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])

        with patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_shipment_execution_complete',
            side_effect=lambda s: str(getattr(s, 'shipment_status', '')).casefold() == 'closed',
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.get_active_shipment_for_driver',
            return_value=backload,
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_backload_leg_pending',
            return_value=False,
        ):
            self.assertTrue(
                should_pivot_closed_shipment_to_active_leg(
                    driver=driver,
                    booking=booking,
                    shipment=outbound,
                )
            )

    def test_pivot_closed_outbound_mutates_context_to_backload_shipment(self):
        driver = SimpleNamespace(pk=1, driver_id=1)
        booking = _booking()
        outbound = _shipment(status='Closed', line='Outbound')
        backload = _shipment(line='Backload', status='Planned')
        backload.pk = 'sh-2'
        backload.shipment_id = 'sh-2'
        booking.shipments = SimpleNamespace(all=lambda: [outbound, backload])
        ctx = SimpleNamespace(
            job_type='shipment',
            job_id='sh-1',
            shipment=outbound,
            booking=booking,
            resolver_meta={},
        )

        with patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_shipment_execution_complete',
            side_effect=lambda s: str(getattr(s, 'shipment_status', '')).casefold() == 'closed',
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.get_active_shipment_for_driver',
            return_value=backload,
        ), patch(
            'mobile_api.helpers.backload_booking_redirect.policy.is_backload_leg_pending',
            return_value=False,
        ):
            self.assertTrue(
                pivot_closed_shipment_to_active_leg(
                    driver=driver,
                    booking=booking,
                    shipment=outbound,
                    context=ctx,
                )
            )
        self.assertEqual(ctx.job_type, 'shipment')
        self.assertEqual(ctx.job_id, 'sh-2')
        self.assertIs(ctx.shipment, backload)
        self.assertTrue(ctx.resolver_meta.get('closed_shipment_active_leg_redirect'))
