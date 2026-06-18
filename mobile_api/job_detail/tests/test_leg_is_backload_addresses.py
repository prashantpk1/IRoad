"""Tests for leg_is_backload_for_addresses helper."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.job_detail.helpers.booking_job_context import (
    leg_is_backload_for_addresses,
    resolve_pending_booking_item_type,
)


class LegIsBackloadForAddressesTests(TestCase):
    def test_outbound_completed_stage_forces_backload_swap(self):
        self.assertTrue(
            leg_is_backload_for_addresses(
                {
                    'show_backload_route': False,
                    'booking_item_type': '',
                    'backload_bootstrap': False,
                    'booking_execution_stage': policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
                },
            )
        )

    def test_pending_booking_item_type_backload(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                    ),
                ],
            ),
        )
        self.assertEqual(resolve_pending_booking_item_type(booking), 'Backload')
