"""Client contract overlap and deletion guard tests."""
from __future__ import annotations

from datetime import date
from unittest import TestCase

from tenant_workspace.client_contract_rules import (
    MSG_DELETE_BLOCKED_TRANSACTIONS,
    MSG_OVERLAPPING_CONTRACT,
    client_contract_delete_block_message,
    client_contract_overlap_field_errors,
    date_ranges_overlap,
)


class DateRangesOverlapTests(TestCase):
    def test_identical_ranges_overlap(self):
        self.assertTrue(
            date_ranges_overlap(
                date(2026, 1, 1),
                date(2026, 12, 31),
                date(2026, 1, 1),
                date(2026, 12, 31),
            )
        )

    def test_partial_overlap_at_start(self):
        self.assertTrue(
            date_ranges_overlap(
                date(2026, 1, 1),
                date(2026, 6, 30),
                date(2026, 6, 1),
                date(2026, 12, 31),
            )
        )

    def test_partial_overlap_at_end(self):
        self.assertTrue(
            date_ranges_overlap(
                date(2026, 7, 1),
                date(2026, 12, 31),
                date(2026, 1, 1),
                date(2026, 7, 15),
            )
        )

    def test_one_day_touch_overlap(self):
        self.assertTrue(
            date_ranges_overlap(
                date(2026, 1, 1),
                date(2026, 6, 30),
                date(2026, 6, 30),
                date(2026, 12, 31),
            )
        )

    def test_adjacent_ranges_do_not_overlap(self):
        self.assertFalse(
            date_ranges_overlap(
                date(2026, 1, 1),
                date(2026, 6, 30),
                date(2026, 7, 1),
                date(2026, 12, 31),
            )
        )

    def test_fully_separated_ranges_do_not_overlap(self):
        self.assertFalse(
            date_ranges_overlap(
                date(2025, 1, 1),
                date(2025, 12, 31),
                date(2026, 1, 1),
                date(2026, 12, 31),
            )
        )

    def test_nested_range_overlap(self):
        self.assertTrue(
            date_ranges_overlap(
                date(2026, 3, 1),
                date(2026, 9, 30),
                date(2026, 1, 1),
                date(2026, 12, 31),
            )
        )


class ClientContractOverlapFieldErrorsTests(TestCase):
    def test_returns_empty_when_dates_missing(self):
        self.assertEqual(
            client_contract_overlap_field_errors(
                client_account_id='acct-1',
                start_date=None,
                end_date=date(2026, 12, 31),
            ),
            {},
        )

    def test_returns_empty_when_end_before_start(self):
        self.assertEqual(
            client_contract_overlap_field_errors(
                client_account_id='acct-1',
                start_date=date(2026, 12, 31),
                end_date=date(2026, 1, 1),
            ),
            {},
        )


class ClientContractDeleteBlockMessageTests(TestCase):
    def test_none_contract_returns_none(self):
        self.assertIsNone(client_contract_delete_block_message(None))

    def test_message_constant_is_user_facing(self):
        self.assertIn('bookings or shipments', MSG_DELETE_BLOCKED_TRANSACTIONS)

    def test_overlap_message_constant_is_user_facing(self):
        self.assertIn('overlaps', MSG_OVERLAPPING_CONTRACT)
