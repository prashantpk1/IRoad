"""Booking detail activity log limit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.views import (
    BOOKING_ACTIVITY_LOG_LIMIT,
    _tenant_booking_activity_entries,
)
from tenant_workspace.models import TenantBooking


class BookingActivityLogLimitTests(SimpleTestCase):
    @patch('iroad_tenants.views.TenantShipment')
    @patch('iroad_tenants.views.TenantOperationActionLog')
    def test_returns_only_latest_ten_entries(self, mock_log_model, mock_shipment_model):
        booking = SimpleNamespace(
            booking_id='booking-1',
            booking_status=TenantBooking.Status.CONFIRMED,
            created_by_label='Ahmed Ali',
            created_at=datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 12, 6, 58, tzinfo=timezone.utc),
        )
        base = datetime(2026, 6, 12, 7, 0, tzinfo=timezone.utc)
        logs = []
        for idx in range(12):
            logs.append(
                SimpleNamespace(
                    shipment_id=f'ship-{idx}',
                    shipment=SimpleNamespace(shipment_no=f'SH-{idx:04d}'),
                    log_date=base + timedelta(minutes=idx),
                    created_at=base + timedelta(minutes=idx),
                    created_by_label='Driver',
                    operation_action=SimpleNamespace(
                        action_code=f'A{idx}',
                        english_label=f'Action {idx}',
                        arabic_label='',
                    ),
                ),
            )
        mock_log_model.objects.filter.return_value.select_related.return_value.order_by.return_value.__getitem__.return_value = logs
        mock_shipment_model.objects.filter.return_value.order_by.return_value = []

        with patch(
            'iroad_tenants.views._tenant_operation_action_log_action_label',
            side_effect=lambda log: log.operation_action.english_label,
        ):
            entries = _tenant_booking_activity_entries(booking)

        self.assertEqual(len(entries), BOOKING_ACTIVITY_LOG_LIMIT)
        self.assertEqual(entries[0]['title'], 'Action 11 (SH-0011)')
        self.assertEqual(entries[-1]['title'], 'Action 2 (SH-0002)')
