"""Tests for backload preshipment cycle scoping."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
    is_backload_leg_pending,
    is_backload_preshipment_cycle,
    resolve_preshipment_booking_item_type,
)


def _shipment(*, line: str, status: str, seq: int = 1):
    return SimpleNamespace(
        pk=uuid4(),
        shipment_id=uuid4(),
        shipment_no=f'SH-{seq}',
        shipment_status=status,
        booking_item_type=line,
        shipment_sequence=seq,
        updated_at=datetime(2026, 6, 17, 20, 36, tzinfo=timezone.utc),
    )


class BookingPreshipmentCycleTests(SimpleTestCase):
    def test_backload_pending_when_outbound_closed_and_no_backload_row(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [_shipment(line='Outbound', status='Closed')],
            ),
        )
        self.assertTrue(is_backload_leg_pending(booking))

    def test_backload_preshipment_cycle_requires_backload_item_type(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [_shipment(line='Outbound', status='Closed')],
            ),
        )
        self.assertTrue(is_backload_preshipment_cycle(booking, 'Backload'))
        self.assertTrue(is_backload_preshipment_cycle(booking, ''))
        self.assertEqual(
            resolve_preshipment_booking_item_type(booking, ''),
            'Backload',
        )
        self.assertFalse(is_backload_preshipment_cycle(booking, 'Outbound'))

    @patch(
        'iroad_tenants.operation_runtime.booking_preshipment_cycle.TenantOperationActionLog'
    )
    def test_preshipment_logs_exclude_outbound_cycle(self, mock_log_model):
        anchor = datetime(2026, 6, 17, 20, 36, tzinfo=timezone.utc)
        outbound = _shipment(line='Outbound', status='Closed')
        booking = SimpleNamespace(
            booking_id=uuid4(),
            pk=uuid4(),
            trip_type='Round',
            shipments=SimpleNamespace(all=lambda: [outbound]),
        )

        qs = MagicMock()
        qs.order_by.return_value = qs
        qs.values_list.return_value = qs
        qs.first.return_value = anchor
        qs.filter.return_value = qs
        qs.exclude.return_value = qs
        mock_log_model.objects.filter.return_value = qs

        from iroad_tenants.operation_runtime.booking_preshipment_cycle import (
            booking_preshipment_logs_queryset,
        )

        booking_preshipment_logs_queryset(booking, booking_item_type='Backload')
        filter_kwargs = qs.filter.call_args.kwargs
        self.assertIn('log_date__gt', filter_kwargs)
        self.assertEqual(filter_kwargs['log_date__gt'], anchor)
