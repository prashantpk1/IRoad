"""Regression tests for booking shipment loading helpers."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.job_detail.helpers.booking_job_context import load_booking_shipments


class LoadBookingShipmentsTests(SimpleTestCase):
    def test_related_manager_fallback_queries_by_booking_id(self):
        manager = MagicMock()
        manager.all.side_effect = RuntimeError('outside tenant schema')

        booking = SimpleNamespace(
            booking_id='b1',
            pk='b1',
            shipments=manager,
        )

        with patch(
            'tenant_workspace.models.TenantShipment.objects.filter',
        ) as mock_filter:
            mock_filter.return_value.order_by.return_value = [SimpleNamespace(pk='s1')]

            rows = load_booking_shipments(booking)

        self.assertEqual(len(rows), 1)
        mock_filter.assert_called_once_with(booking_id='b1')

    def test_prefetched_list_is_returned_as_is(self):
        booking = SimpleNamespace(shipments=[SimpleNamespace(pk='s1')])

        rows = load_booking_shipments(booking)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].pk, 's1')
