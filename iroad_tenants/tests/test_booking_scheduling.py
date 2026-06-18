"""Unit tests for booking duplicate prevention (PCS §3.8)."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from iroad_tenants.booking_scheduling import (
    _driver_blocks_on_booking,
    _pair_blocks_on_booking,
    _truck_blocks_on_booking,
    scheduling_conflict_messages,
)


def _booking(
    *,
    trip_type='One-Way',
    status='Confirmed',
    truck_id=None,
    driver_id=None,
    backload_truck_id=None,
    backload_driver_id=None,
):
    return SimpleNamespace(
        trip_type=trip_type,
        booking_status=status,
        assigned_truck_id=truck_id,
        assigned_driver_id=driver_id,
        booking_line_backload_truck_id=backload_truck_id,
        booking_line_backload_driver_id=backload_driver_id,
        pk='booking-1',
    )


class BookingSchedulingHelpersTests(TestCase):
    @patch('iroad_tenants.booking_scheduling.derive_booking_line_status')
    def test_truck_blocks_when_open_outbound_line_uses_truck(self, derive_status):
        derive_status.return_value = 'Confirmed'
        booking = _booking(truck_id='truck-a', driver_id='driver-x')
        truck = SimpleNamespace(pk='truck-a', truck_code='TR-0001')
        self.assertTrue(_truck_blocks_on_booking(booking, truck))

    @patch('iroad_tenants.booking_scheduling.derive_booking_line_status')
    def test_truck_does_not_block_when_line_completed(self, derive_status):
        derive_status.return_value = 'Completed'
        booking = _booking(truck_id='truck-a')
        truck = SimpleNamespace(pk='truck-a', truck_code='TR-0001')
        self.assertFalse(_truck_blocks_on_booking(booking, truck))

    @patch('iroad_tenants.booking_scheduling.derive_booking_line_status')
    def test_driver_blocks_on_backload_line(self, derive_status):
        def _status(_booking, line_type):
            return 'In Progress' if line_type == 'Backload' else 'Completed'

        derive_status.side_effect = _status
        booking = _booking(
            trip_type='Round',
            truck_id='truck-1',
            driver_id='driver-1',
            backload_truck_id='truck-2',
            backload_driver_id='driver-2',
        )
        driver = SimpleNamespace(pk='driver-2', driver_code='DR-0002')
        self.assertTrue(_driver_blocks_on_booking(booking, driver))

    @patch('iroad_tenants.booking_scheduling.derive_booking_line_status')
    def test_pair_requires_both_on_same_line(self, derive_status):
        derive_status.return_value = 'Confirmed'
        booking = _booking(truck_id='truck-a', driver_id='driver-b')
        truck = SimpleNamespace(pk='truck-a', truck_code='TR-0001')
        driver = SimpleNamespace(pk='driver-c', driver_code='DR-0003')
        self.assertFalse(_pair_blocks_on_booking(booking, truck, driver))


class SchedulingConflictMessagesTests(TestCase):
    @patch('iroad_tenants.booking_scheduling._truck_conflict')
    @patch('iroad_tenants.booking_scheduling._driver_conflict')
    @patch('iroad_tenants.booking_scheduling._pair_conflict')
    def test_emits_separate_truck_driver_and_pair_messages(
        self,
        pair_conflict,
        driver_conflict,
        truck_conflict,
    ):
        truck = SimpleNamespace(pk='t1', truck_code='TR-0001')
        driver = SimpleNamespace(pk='d1', driver_code='DR-0001')
        truck_conflict.return_value = True
        driver_conflict.return_value = True
        pair_conflict.return_value = True

        messages = scheduling_conflict_messages(
            booking_date='2026-06-18',
            truck=truck,
            driver=driver,
        )

        self.assertEqual(len(messages), 3)
        self.assertIn('Outbound line: Truck TR-0001', messages[0])
        self.assertIn('Outbound line: Driver DR-0001', messages[1])
        self.assertIn('Duplicate assignment on Outbound line', messages[2])

    def test_empty_when_no_date(self):
        self.assertEqual(
            scheduling_conflict_messages(
                booking_date=None,
                truck=SimpleNamespace(pk='t1', truck_code='TR-0001'),
            ),
            [],
        )
