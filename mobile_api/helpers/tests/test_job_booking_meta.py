"""Tests for client_name and execution_date helpers."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from mobile_api.helpers.job_booking_meta import (
    resolve_client_name,
    resolve_execution_date,
    resolve_execution_time,
)


class JobBookingMetaTests(SimpleTestCase):
    def test_client_name_from_booking(self):
        booking = SimpleNamespace(
            client_account=SimpleNamespace(
                display_name='Acme Corp',
                name_english='Acme EN',
                name_arabic='',
            ),
        )
        self.assertEqual(
            resolve_client_name(booking=booking),
            'Acme Corp',
        )

    def test_execution_date_prefers_execution_over_booking_date(self):
        booking = SimpleNamespace(
            execution_date=date(2026, 5, 15),
            booking_date=date(2026, 5, 1),
        )
        self.assertEqual(
            resolve_execution_date(booking=booking),
            '2026-05-15',
        )

    def test_execution_date_falls_back_to_booking_date(self):
        booking = SimpleNamespace(
            execution_date=None,
            booking_date=date(2026, 5, 1),
        )
        self.assertEqual(
            resolve_execution_date(booking=booking),
            '2026-05-01',
        )

    def test_execution_date_from_movement_date_before_start(self):
        movement = SimpleNamespace(
            start_time=None,
            movement_date=date(2026, 6, 30),
        )
        self.assertEqual(
            resolve_execution_date(movement=movement),
            '2026-06-30',
        )
        self.assertEqual(resolve_execution_time(movement=movement), '')

    def test_execution_date_and_time_from_movement_start_time(self):
        started = timezone.make_aware(
            datetime(2026, 6, 30, 10, 30, 24),
            timezone.get_current_timezone(),
        )
        movement = SimpleNamespace(
            start_time=started,
            movement_date=date(2026, 6, 29),
        )
        self.assertEqual(
            resolve_execution_date(movement=movement),
            '2026-06-30',
        )
        self.assertEqual(
            resolve_execution_time(movement=movement),
            timezone.localtime(started).strftime('%H:%M:%S'),
        )
