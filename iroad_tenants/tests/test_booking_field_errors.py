"""Booking form field-error mapping tests."""
from __future__ import annotations

from unittest import TestCase

from iroad_tenants.views import _tenant_booking_field_errors_from_messages


class BookingFieldErrorsFromMessagesTests(TestCase):
    def test_scheduling_conflict_highlights_truck_and_driver_not_booking_date(self):
        msg = (
            'Another booking is already in progress for the selected truck and driver '
            'on this date (operational status Planned or In Execution).'
        )
        field_errors = _tenant_booking_field_errors_from_messages([msg])
        self.assertIn('booking_line_truck_1', field_errors)
        self.assertIn('booking_line_driver_1', field_errors)
        self.assertNotIn('booking_date', field_errors)

    def test_scheduled_booking_date_rule_maps_to_booking_date(self):
        msg = 'Scheduled bookings must have a booking date after today.'
        field_errors = _tenant_booking_field_errors_from_messages([msg])
        self.assertEqual(field_errors.get('booking_date'), msg)
        self.assertNotIn('booking_line_truck_1', field_errors)

    def test_execution_before_booking_maps_to_execution_date(self):
        msg = 'Execution date cannot be before the booking date.'
        field_errors = _tenant_booking_field_errors_from_messages([msg])
        self.assertEqual(field_errors.get('execution_date'), msg)
        self.assertNotIn('booking_date', field_errors)
