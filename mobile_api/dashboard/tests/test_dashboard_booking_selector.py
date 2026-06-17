"""
Unit tests for dashboard booking selection and projection.

Uses mocks (no tenant DB) for policy and projection; selector ordering tests
patch the ORM queryset.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.db.models.query import ModelIterable

from mobile_api.dashboard.projections.booking_projection import (
    build_booking_card,
    build_booking_card_from_selection,
)
from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.dashboard.selectors.dashboard_booking_selector import (
    DashboardBookingSelector,
    select_current_driver_booking,
)
from tenant_workspace.models import TenantBooking, TenantShipment


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid4()
    d.driver_id = d.pk
    return d


def _booking(
    *,
    trip_type='One-Way',
    booking_date=None,
    execution_date=None,
    status=TenantBooking.Status.CONFIRMED,
    assigned_driver_id=None,
    backload_driver_id=None,
):
    b = MagicMock()
    b.pk = uuid4()
    b.booking_id = b.pk
    b.booking_no = 'BK-100'
    b.trip_type = trip_type
    b.booking_status = status
    b.booking_date = booking_date or date(2026, 5, 20)
    b.execution_date = execution_date
    b.assigned_driver_id = assigned_driver_id
    b.booking_line_backload_driver_id = backload_driver_id
    b.shipments = MagicMock()
    b.shipments.all = MagicMock(return_value=[])
    return b


def _shipment(
    *,
    booking_item_type='Outbound',
    status=TenantShipment.ShipmentStatus.LOADED,
    sequence=1,
    driver_id=None,
    shipment_no='SH-1',
):
    s = MagicMock()
    s.pk = uuid4()
    s.shipment_id = s.pk
    s.shipment_no = shipment_no
    s.booking_item_type = booking_item_type
    s.shipment_status = status
    s.shipment_sequence = sequence
    s.driver_id = driver_id
    s.trip_type = ''
    return s


def _mock_shipments_prefetch_qs():
    qs = MagicMock()
    qs._iterable_class = ModelIterable
    qs.select_related.return_value = qs
    qs.order_by.return_value = qs
    return qs


def _mock_booking_queryset(bookings):
    """Mock ORM chain ending in a sliceable prefetch result."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.distinct.return_value = qs
    qs.order_by.return_value = qs
    prefetched = list(bookings)

    class _Sliceable:
        def __getitem__(self, item):
            if isinstance(item, slice):
                return prefetched[item]
            return prefetched[item]

    qs.prefetch_related.return_value = _Sliceable()
    qs.select_related.return_value = qs
    return qs


class BookingSelectionPolicyTests(SimpleTestCase):
    def test_execution_complete_delivered_and_closed(self):
        self.assertTrue(
            policy.is_shipment_execution_complete(
                _shipment(status=TenantShipment.ShipmentStatus.DELIVERED)
            )
        )
        self.assertTrue(
            policy.is_shipment_execution_complete(
                _shipment(status=TenantShipment.ShipmentStatus.CLOSED)
            )
        )
        self.assertFalse(
            policy.is_shipment_execution_complete(
                _shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)
            )
        )

    def test_business_complete_closed_only(self):
        self.assertTrue(
            policy.is_shipment_business_complete(
                _shipment(status=TenantShipment.ShipmentStatus.CLOSED)
            )
        )
        self.assertFalse(
            policy.is_shipment_business_complete(
                _shipment(status=TenantShipment.ShipmentStatus.DELIVERED)
            )
        )

    def test_single_shipment_active_and_progress(self):
        driver = _driver()
        booking = _booking(assigned_driver_id=driver.pk)
        shipments = [_shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)]

        active = policy.get_active_shipment_for_driver(driver, booking, shipments)
        total, exec_completed, exec_pct = policy.booking_execution_progress(shipments)
        _, biz_completed, biz_pct = policy.booking_business_progress(shipments)

        self.assertIs(active, shipments[0])
        self.assertEqual(total, 1)
        self.assertEqual(exec_completed, 0)
        self.assertEqual(biz_completed, 0)
        self.assertEqual(exec_pct, 0)
        self.assertEqual(biz_pct, 0)
        self.assertFalse(policy.is_booking_fully_complete(shipments))

    def test_cancelled_shipment_excluded_from_progress(self):
        shipments = [
            _shipment(status=TenantShipment.ShipmentStatus.CANCELLED),
            _shipment(
                status=TenantShipment.ShipmentStatus.CLOSED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        total, exec_completed, exec_pct = policy.booking_execution_progress(shipments)
        _, biz_completed, biz_pct = policy.booking_business_progress(shipments)

        self.assertEqual(total, 1)
        self.assertEqual(exec_completed, 1)
        self.assertEqual(biz_completed, 1)
        self.assertEqual(exec_pct, 100)
        self.assertEqual(biz_pct, 100)

    def test_booking_fully_complete_requires_all_legs_closed(self):
        shipments = [
            _shipment(status=TenantShipment.ShipmentStatus.CLOSED),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.CLOSED,
                sequence=2,
            ),
        ]
        self.assertTrue(policy.is_booking_fully_complete(shipments))

    def test_booking_not_fully_complete_when_delivered_not_closed(self):
        shipments = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.CLOSED,
                sequence=2,
            ),
        ]
        self.assertFalse(policy.is_booking_fully_complete(shipments))

    def test_round_trip_next_executable_outbound_before_backload(self):
        booking = _booking(trip_type='Round')
        shipments = [
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
            ),
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.IN_TRANSIT,
                sequence=1,
            ),
        ]
        nxt = policy.get_next_executable_shipment(booking, shipments)
        self.assertEqual(nxt.booking_item_type, 'Outbound')

    def test_round_trip_delivered_outbound_activates_backload_same_driver(self):
        driver = _driver()
        booking = _booking(
            trip_type='Round',
            assigned_driver_id=driver.pk,
            backload_driver_id=driver.pk,
        )
        shipments = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        active = policy.get_active_shipment_for_driver(driver, booking, shipments)
        self.assertEqual(active.booking_item_type, 'Backload')

        exec_total, exec_completed, exec_pct = policy.booking_execution_progress(
            shipments
        )
        _, biz_completed, biz_pct = policy.booking_business_progress(shipments)
        self.assertEqual(exec_total, 2)
        self.assertEqual(exec_completed, 1)
        self.assertEqual(exec_pct, 50)
        self.assertEqual(biz_completed, 0)
        self.assertEqual(biz_pct, 0)

    def test_round_trip_advances_to_backload_after_outbound_closed(self):
        driver = _driver()
        booking = _booking(
            trip_type='Round',
            assigned_driver_id=driver.pk,
            backload_driver_id=driver.pk,
        )
        shipments = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.CLOSED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        active = policy.get_active_shipment_for_driver(driver, booking, shipments)
        self.assertEqual(active.booking_item_type, 'Backload')

        exec_total, exec_completed, exec_pct = policy.booking_execution_progress(
            shipments
        )
        _, biz_completed, biz_pct = policy.booking_business_progress(shipments)
        self.assertEqual(exec_total, 2)
        self.assertEqual(exec_completed, 1)
        self.assertEqual(exec_pct, 50)
        self.assertEqual(biz_completed, 1)
        self.assertEqual(biz_pct, 50)

    def test_split_driver_round_trip_backload_driver_gets_delivered_handoff(self):
        outbound_driver = _driver()
        backload_driver = _driver()
        booking = _booking(
            trip_type='Round',
            assigned_driver_id=outbound_driver.pk,
            backload_driver_id=backload_driver.pk,
        )
        shipments = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
                driver_id=outbound_driver.pk,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
                shipment_no='SH-2',
                driver_id=backload_driver.pk,
            ),
        ]
        active_backload = policy.get_active_shipment_for_driver(
            backload_driver, booking, shipments
        )
        active_outbound = policy.get_active_shipment_for_driver(
            outbound_driver, booking, shipments
        )
        self.assertEqual(active_backload.booking_item_type, 'Backload')
        self.assertIsNone(active_outbound)

    def test_booking_ordering_key_uses_line_type_rank(self):
        ordered = policy.sorted_shipments(
            [
                _shipment(booking_item_type='Backload', sequence=1),
                _shipment(booking_item_type='Outbound', sequence=1),
            ]
        )
        self.assertEqual(ordered[0].booking_item_type, 'Outbound')


class BookingProjectionTests(SimpleTestCase):
    def test_build_booking_card_from_selection(self):
        driver = _driver()
        booking = _booking(trip_type='Round', assigned_driver_id=driver.pk)
        outbound = _shipment(booking_item_type='Outbound')
        selection = DriverBookingSelectionResult(
            booking=booking,
            active_shipment=outbound,
            next_executable_shipment=outbound,
            shipments=[outbound],
            shipments_total=2,
            shipments_execution_completed=1,
            shipments_business_completed=0,
            execution_progress_percentage=50,
            business_progress_percentage=0,
            shipments_completed=1,
            progress_percentage=50,
            booking_execution_stage=policy.BOOKING_EXECUTION_STAGE_PARTIAL,
        )
        card = build_booking_card_from_selection(selection)

        self.assertEqual(card['booking_no'], 'BK-100')
        self.assertEqual(card['trip_type'], 'Round')
        self.assertEqual(card['shipments_total'], 2)
        self.assertEqual(card['shipments_execution_completed'], 1)
        self.assertEqual(card['shipments_business_completed'], 0)
        self.assertEqual(card['execution_progress_percentage'], 50)
        self.assertEqual(card['business_progress_percentage'], 0)
        self.assertEqual(card['progress_percentage'], 50)
        self.assertEqual(card['active_shipment']['shipment_no'], 'SH-1')
        self.assertEqual(
            card['booking_execution_stage'],
            policy.BOOKING_EXECUTION_STAGE_PARTIAL,
        )
        self.assertIn('round_trip', card)

    def test_build_booking_card_derives_dual_progress_without_selection(self):
        driver = _driver()
        booking = _booking(
            trip_type='Round',
            assigned_driver_id=driver.pk,
            backload_driver_id=driver.pk,
        )
        shipments = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        booking.shipments.all.return_value = shipments
        card = build_booking_card(booking, driver=driver)

        self.assertEqual(card['execution_progress_percentage'], 50)
        self.assertEqual(card['business_progress_percentage'], 0)
        self.assertEqual(card['active_shipment']['shipment_no'], 'SH-2')
        self.assertEqual(
            card['booking_execution_stage'],
            policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
        )


class DashboardBookingSelectorTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        shipment_patcher = patch(
            'mobile_api.dashboard.selectors.dashboard_booking_selector.TenantShipment'
        )
        self.mock_shipment_model = shipment_patcher.start()
        self.addCleanup(shipment_patcher.stop)
        self.mock_shipment_model.objects.select_related.return_value.order_by.return_value = (
            _mock_shipments_prefetch_qs()
        )

    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.DashboardBookingSelector._auto_shipment_bootstrap_enabled',
        return_value=False,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.TenantBooking'
    )
    def test_select_skips_fully_completed_booking(self, mock_booking_model, _bootstrap):
        driver = _driver()
        done = _booking(assigned_driver_id=driver.pk, booking_date=date(2026, 5, 1))
        done.shipments.all.return_value = [
            _shipment(status=TenantShipment.ShipmentStatus.CLOSED),
        ]
        active = _booking(
            assigned_driver_id=driver.pk,
            booking_date=date(2026, 5, 10),
        )
        active.shipments.all.return_value = [
            _shipment(status=TenantShipment.ShipmentStatus.LOADED),
        ]

        mock_booking_model.objects.filter.return_value = _mock_booking_queryset(
            [done, active]
        )

        result = DashboardBookingSelector().select_current_driver_booking(driver)
        self.assertIs(result.booking, active)

    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.DashboardBookingSelector._auto_shipment_bootstrap_enabled',
        return_value=False,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.TenantBooking'
    )
    def test_select_keeps_booking_when_outbound_delivered_backload_open(
        self, mock_booking_model, _bootstrap
    ):
        driver = _driver()
        round_trip = _booking(
            trip_type='Round',
            assigned_driver_id=driver.pk,
            backload_driver_id=driver.pk,
            booking_date=date(2026, 5, 10),
        )
        round_trip.shipments.all.return_value = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]

        mock_booking_model.objects.filter.return_value = _mock_booking_queryset(
            [round_trip]
        )

        result = DashboardBookingSelector().select_current_driver_booking(driver)
        self.assertIsNotNone(result)
        self.assertEqual(result.active_shipment.booking_item_type, 'Backload')
        self.assertEqual(result.execution_progress_percentage, 50)
        self.assertEqual(result.business_progress_percentage, 0)
        self.assertEqual(
            result.booking_execution_stage,
            policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
        )

    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.DashboardBookingSelector._auto_shipment_bootstrap_enabled',
        return_value=False,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.TenantBooking'
    )
    def test_select_returns_none_when_no_assignments(self, mock_booking_model, _bootstrap):
        driver = _driver()
        mock_booking_model.objects.filter.return_value = _mock_booking_queryset([])

        self.assertIsNone(select_current_driver_booking(driver))

    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.DashboardBookingSelector._auto_shipment_bootstrap_enabled',
        return_value=True,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.TenantBooking'
    )
    def test_select_booking_without_shipment_when_autoshipment_bootstrap_enabled(
        self, mock_booking_model, _mock_bootstrap
    ):
        driver = _driver()
        booking_only = _booking(
            assigned_driver_id=driver.pk,
            booking_date=date(2026, 6, 17),
        )
        booking_only.shipments.all.return_value = []

        mock_booking_model.objects.filter.return_value = _mock_booking_queryset(
            [booking_only]
        )

        result = DashboardBookingSelector().select_current_driver_booking(driver)
        self.assertIsNotNone(result)
        self.assertIs(result.booking, booking_only)
        self.assertIsNone(result.active_shipment)
        self.assertEqual(
            result.booking_execution_stage,
            policy.BOOKING_EXECUTION_STAGE_NOT_STARTED,
        )

    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.DashboardBookingSelector._auto_shipment_bootstrap_enabled',
        return_value=False,
    )
    @patch(
        'mobile_api.dashboard.selectors.dashboard_booking_selector.TenantBooking'
    )
    def test_booking_ordering_picks_earlier_date_first(self, mock_booking_model, _bootstrap):
        driver = _driver()
        later = _booking(
            assigned_driver_id=driver.pk,
            booking_date=date(2026, 6, 1),
        )
        later.shipments.all.return_value = [
            _shipment(status=TenantShipment.ShipmentStatus.LOADED),
        ]
        earlier = _booking(
            assigned_driver_id=driver.pk,
            booking_date=date(2026, 5, 1),
        )
        earlier.shipments.all.return_value = [
            _shipment(
                status=TenantShipment.ShipmentStatus.LOADED,
                shipment_no='SH-EARLY',
            ),
        ]

        mock_booking_model.objects.filter.return_value = _mock_booking_queryset(
            [earlier, later]
        )

        result = DashboardBookingSelector().select_current_driver_booking(driver)
        self.assertEqual(result.active_shipment.shipment_no, 'SH-EARLY')


class BookingExecutionStageTests(SimpleTestCase):
    """``derive_booking_execution_stage`` + deterministic sequencing."""

    def test_outbound_only_one_way_not_started(self):
        booking = _booking(trip_type='One-Way')
        legs = [_shipment(status=TenantShipment.ShipmentStatus.LOADED)]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_NOT_STARTED,
        )

    def test_fully_closed_business_completed(self):
        booking = _booking(trip_type='Round')
        legs = [
            _shipment(status=TenantShipment.ShipmentStatus.CLOSED, sequence=1),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.CLOSED,
                sequence=2,
            ),
        ]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_BUSINESS_COMPLETED,
        )

    def test_execution_completed_all_delivered_not_all_closed(self):
        booking = _booking(trip_type='One-Way')
        legs = [
            _shipment(status=TenantShipment.ShipmentStatus.DELIVERED, sequence=1),
            _shipment(
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_EXECUTION_COMPLETED,
        )

    def test_round_trip_outbound_completed_backload_queued(self):
        booking = _booking(trip_type='Round')
        legs = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
        )

    def test_round_trip_backload_active_on_road(self):
        booking = _booking(trip_type='Round')
        legs = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.DELIVERED,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.IN_TRANSIT,
                sequence=2,
                shipment_no='SH-2',
            ),
        ]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_BACKLOAD_ACTIVE,
        )

    def test_cancelled_outbound_only_backload_countable(self):
        booking = _booking(trip_type='Round')
        legs = [
            _shipment(status=TenantShipment.ShipmentStatus.CANCELLED, sequence=1),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
            ),
        ]
        ordered = policy.sorted_countable_shipments(legs)
        self.assertEqual(len(ordered), 1)
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED,
        )

    def test_partially_completed_one_way_in_transit(self):
        booking = _booking(trip_type='One-Way')
        legs = [_shipment(status=TenantShipment.ShipmentStatus.IN_TRANSIT)]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_PARTIAL,
        )

    def test_split_driver_round_trip_outbound_in_transit_is_partial(self):
        booking = _booking(trip_type='Round')
        legs = [
            _shipment(
                booking_item_type='Outbound',
                status=TenantShipment.ShipmentStatus.IN_TRANSIT,
                sequence=1,
            ),
            _shipment(
                booking_item_type='Backload',
                status=TenantShipment.ShipmentStatus.LOADED,
                sequence=2,
            ),
        ]
        self.assertEqual(
            policy.derive_booking_execution_stage(booking, legs),
            policy.BOOKING_EXECUTION_STAGE_PARTIAL,
        )
