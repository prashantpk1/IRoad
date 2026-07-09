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


def _shipment(*, line: str, status: str, seq: int = 1, created_at=None):
    created = created_at or datetime(2026, 6, 17, 8, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        pk=uuid4(),
        shipment_id=uuid4(),
        shipment_no=f'SH-{seq}',
        shipment_status=status,
        booking_item_type=line,
        shipment_sequence=seq,
        created_at=created,
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

    def test_backload_pending_when_outbound_cancelled_and_no_backload_row(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [_shipment(line='Outbound', status='Cancelled')],
            ),
        )
        self.assertTrue(is_backload_leg_pending(booking))
        self.assertEqual(
            resolve_preshipment_booking_item_type(booking, ''),
            'Backload',
        )
        self.assertTrue(is_backload_preshipment_cycle(booking, 'Backload'))

    def test_explicit_outbound_hint_redirects_to_backload_when_pending(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [_shipment(line='Outbound', status='Cancelled')],
            ),
        )
        self.assertEqual(
            resolve_preshipment_booking_item_type(booking, 'Outbound'),
            'Backload',
        )

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
        self.assertTrue(is_backload_preshipment_cycle(booking, 'Outbound'))

    def test_backload_preshipment_cycle_when_backload_row_exists(self):
        booking = SimpleNamespace(
            trip_type='Round',
            shipments=SimpleNamespace(
                all=lambda: [
                    _shipment(line='Outbound', status='Closed'),
                    _shipment(line='Backload', status='Created'),
                ],
            ),
        )
        self.assertFalse(is_backload_leg_pending(booking))
        self.assertTrue(is_backload_preshipment_cycle(booking, 'Backload'))
        self.assertTrue(is_backload_preshipment_cycle(booking, 'Outbound'))
        self.assertEqual(resolve_preshipment_booking_item_type(booking, ''), 'Backload')
        self.assertEqual(
            resolve_preshipment_booking_item_type(booking, 'Outbound'),
            'Backload',
        )

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
        filter_kwargs_list = [call.kwargs for call in qs.filter.call_args_list]
        self.assertTrue(any('log_date__gt' in kwargs for kwargs in filter_kwargs_list))
        self.assertTrue(any(kwargs.get('log_date__gt') == anchor for kwargs in filter_kwargs_list))
        self.assertTrue(any('log_date__gte' in kwargs for kwargs in filter_kwargs_list))

    def test_outbound_preshipment_before_shipment_birth_excluded_from_backload(self):
        """BK-0066 class bug: outbound A1–A3 must not count as backload Start Job."""
        birth_at = datetime(2026, 6, 23, 7, 30, tzinfo=timezone.utc)
        anchor = datetime(2026, 6, 23, 10, 0, tzinfo=timezone.utc)
        outbound_log = datetime(2026, 6, 23, 7, 25, tzinfo=timezone.utc)
        self.assertFalse(outbound_log > anchor and outbound_log >= birth_at)

    def test_backload_cycle_anchor_excludes_preshipment_before_outbound_complete(self):
        anchor = datetime(2026, 6, 23, 10, 0, tzinfo=timezone.utc)
        outbound = _shipment(line='Outbound', status='Closed')
        booking = SimpleNamespace(
            booking_id=uuid4(),
            pk=uuid4(),
            trip_type='Round',
            shipments=SimpleNamespace(all=lambda: [outbound]),
        )

        with patch(
            'iroad_tenants.operation_runtime.booking_preshipment_cycle.TenantOperationActionLog'
        ) as mock_log_model, patch(
            'iroad_tenants.operation_runtime.booking_preshipment_cycle.outbound_execution_complete_anchor',
            return_value=anchor,
        ):
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
            filter_kwargs_list = [call.kwargs for call in qs.filter.call_args_list]
            self.assertTrue(
                any(kwargs.get('log_date__gt') == anchor for kwargs in filter_kwargs_list)
            )

    def test_backload_cycle_start_job_not_waived_without_log(self):
        from iroad_tenants.operation_execution import _booking_start_job_done

        outbound = _shipment(line='Outbound', status='Closed')
        booking = SimpleNamespace(
            booking_id=uuid4(),
            pk=uuid4(),
            trip_type='Round',
            shipments=SimpleNamespace(all=lambda: [outbound]),
        )

        qs = MagicMock()
        qs.select_related.return_value.__getitem__.return_value = []
        with patch(
            'iroad_tenants.operation_execution.booking_preshipment_logs_queryset',
            return_value=qs,
        ):
            self.assertFalse(
                _booking_start_job_done(booking, booking_item_type='Backload'),
            )
