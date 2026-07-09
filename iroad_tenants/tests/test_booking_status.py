"""Booking derived status and cancel guard tests."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from functools import wraps
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from unittest import TestCase

from iroad_tenants.booking_status import (
    BOOKING_HEADER_COMPLETED,
    BOOKING_HEADER_CONFIRMED,
    BOOKING_HEADER_IN_PROGRESS,
    BOOKING_HEADER_PARTIALLY_COMPLETED,
    BOOKING_ITEM_COMPLETED,
    BOOKING_ITEM_CONFIRMED,
    BOOKING_ITEM_IN_PROGRESS,
    booking_cancel_guard_errors,
    booking_can_cancel,
    derive_booking_header_status,
    derive_booking_line_status,
)


def _booking(**overrides):
    booking = SimpleNamespace(
        booking_id=uuid4(),
        booking_status='Confirmed',
        trip_type='Round',
        route_direction='forward',
    )
    for key, value in overrides.items():
        setattr(booking, key, value)
    return booking


@contextmanager
def _patch_tenant_shipment_objects(mock_objects=None):
    """Patch TenantShipment.objects without importing Django models."""
    shipment_objects = mock_objects if mock_objects is not None else MagicMock()
    models_module = MagicMock()
    models_module.TenantShipment = MagicMock(objects=shipment_objects)
    with patch.dict(
        sys.modules,
        {'tenant_workspace.models': models_module},
    ):
        yield shipment_objects


def _patch_shipment_objects(test_func):
    @wraps(test_func)
    def wrapper(self, *args, **kwargs):
        mock_objects = MagicMock()
        with _patch_tenant_shipment_objects(mock_objects):
            return test_func(self, mock_objects, *args, **kwargs)

    return wrapper


class BookingStatusDerivationTests(TestCase):
    def test_confirmed_booking_without_shipments_is_confirmed(self):
        booking = _booking()
        with _patch_tenant_shipment_objects() as mock_objects:
            mock_objects.filter.return_value.exists.return_value = False
            self.assertEqual(derive_booking_line_status(booking, 'Outbound'), BOOKING_ITEM_CONFIRMED)
            self.assertEqual(derive_booking_header_status(booking), BOOKING_HEADER_CONFIRMED)

    @_patch_shipment_objects
    def test_open_shipment_marks_line_in_progress(self, mock_objects):
        booking = _booking()
        qs = MagicMock()
        qs.exists.return_value = True
        qs.exclude.return_value.exists.return_value = True
        qs.filter.return_value.exists.return_value = False
        mock_objects.filter.return_value = qs

        self.assertEqual(derive_booking_line_status(booking, 'Outbound'), BOOKING_ITEM_IN_PROGRESS)
        self.assertEqual(derive_booking_header_status(booking), BOOKING_HEADER_IN_PROGRESS)

    @_patch_shipment_objects
    def test_one_completed_one_planned_is_partially_completed(self, mock_objects):
        booking = _booking(trip_type='Round')

        def _filter_side_effect(**kwargs):
            line_type = kwargs.get('booking_item_type')
            qs = MagicMock()
            terminal = ('Cancelled', 'Closed')
            if line_type == 'Outbound':
                qs.exists.return_value = True
                qs.exclude.return_value.exists.return_value = False
                qs.filter.side_effect = lambda **kw: MagicMock(
                    exists=MagicMock(
                        return_value=kw.get('shipment_status') == 'Closed',
                    ),
                )
                return qs
            if line_type == 'Backload':
                qs.exists.return_value = False
                return qs
            return qs

        mock_objects.filter.side_effect = _filter_side_effect
        self.assertEqual(derive_booking_header_status(booking), BOOKING_HEADER_PARTIALLY_COMPLETED)

    @_patch_shipment_objects
    def test_one_delivered_one_planned_is_partially_completed(self, mock_objects):
        booking = _booking(trip_type='Round')

        def _filter_side_effect(**kwargs):
            line_type = kwargs.get('booking_item_type')
            qs = MagicMock()
            if line_type == 'Outbound':
                qs.exists.return_value = True
                qs.exclude.return_value.exists.return_value = False
                qs.filter.side_effect = lambda **kw: MagicMock(
                    exists=MagicMock(
                        return_value=kw.get('shipment_status') == 'Delivered',
                    ),
                )
                return qs
            if line_type == 'Backload':
                qs.exists.return_value = False
                return qs
            return qs

        mock_objects.filter.side_effect = _filter_side_effect
        self.assertEqual(derive_booking_header_status(booking), BOOKING_HEADER_PARTIALLY_COMPLETED)

    @_patch_shipment_objects
    def test_all_lines_completed_is_completed(self, mock_objects):
        booking = _booking(trip_type='One-Way')
        qs = MagicMock()
        qs.exists.return_value = True
        qs.exclude.return_value.exists.return_value = False
        qs.filter.side_effect = lambda **kw: MagicMock(
            exists=MagicMock(return_value=kw.get('shipment_status') == 'Closed'),
        )
        mock_objects.filter.return_value = qs

        self.assertEqual(derive_booking_line_status(booking, 'Outbound'), BOOKING_ITEM_COMPLETED)
        self.assertEqual(derive_booking_header_status(booking), BOOKING_HEADER_COMPLETED)


class BookingCancelGuardTests(TestCase):
    @_patch_shipment_objects
    def test_cancel_allowed_when_only_cancelled_shipments_exist(self, mock_objects):
        booking = _booking()
        mock_objects.filter.return_value.exclude.return_value.exists.return_value = False
        self.assertTrue(booking_can_cancel(booking))
        self.assertEqual(
            booking_cancel_guard_errors(booking, 'Cancelled'),
            [],
        )

    @_patch_shipment_objects
    def test_cancel_blocked_when_active_shipment_exists(self, mock_objects):
        booking = _booking()
        mock_objects.filter.return_value.exclude.return_value.exists.return_value = True
        self.assertFalse(booking_can_cancel(booking))
        self.assertTrue(booking_cancel_guard_errors(booking, 'Cancelled'))


class BookingStatusSyncAfterItemChangeTests(TestCase):
    def test_sync_sets_cancelled_when_derived_cancelled(self):
        booking = _booking(booking_status='Confirmed', trip_type='One-Way')
        with _patch_tenant_shipment_objects() as mock_objects:
            qs = MagicMock()
            qs.exists.return_value = True
            qs.exclude.return_value.exists.return_value = False
            qs.filter.side_effect = lambda **kw: MagicMock(
                exists=MagicMock(return_value=kw.get('shipment_status') == 'Cancelled'),
            )
            mock_objects.filter.return_value = qs
            from iroad_tenants.booking_status import sync_booking_status_after_item_change

            sync_booking_status_after_item_change(booking, save=False)
            self.assertEqual(booking.booking_status, 'Cancelled')

    def test_sync_sets_completed_when_derived_completed(self):
        booking = _booking(booking_status='Confirmed', trip_type='One-Way')
        with _patch_tenant_shipment_objects() as mock_objects:
            qs = MagicMock()
            qs.exists.return_value = True
            qs.exclude.return_value.exists.return_value = False
            qs.filter.side_effect = lambda **kw: MagicMock(
                exists=MagicMock(
                    return_value=kw.get('shipment_status') in {'Closed', 'Delivered'},
                ),
            )
            mock_objects.filter.return_value = qs
            from iroad_tenants.booking_status import sync_booking_status_after_item_change

            sync_booking_status_after_item_change(booking, save=False)
            self.assertEqual(booking.booking_status, 'Completed')

    def test_sync_leaves_confirmed_when_line_still_open(self):
        booking = _booking(booking_status='Confirmed', trip_type='One-Way')
        with _patch_tenant_shipment_objects() as mock_objects:
            mock_objects.filter.return_value.exists.return_value = False
            from iroad_tenants.booking_status import sync_booking_status_after_item_change

            sync_booking_status_after_item_change(booking, save=False)
            self.assertEqual(booking.booking_status, 'Confirmed')
