"""
mobile_api/dashboard/selectors/dashboard_booking_selector.py

Booking-centric driver job selection for the unified dashboard.

Client rule: one current job; ordered by booking/execution date; skip bookings
that are business-complete (all non-cancelled legs CLOSED).
"""
from __future__ import annotations

from typing import Any

from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Prefetch, Q
from django.db.models.functions import Coalesce
from django.test.testcases import DatabaseOperationForbidden

from tenant_workspace.models import TenantBooking, TenantOperationAction, TenantShipment

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.polling_constants import DASHBOARD_BOOKING_CANDIDATE_LIMIT
from mobile_api.dashboard.selectors import booking_selection_policy as policy

# Shipments still eligible for driver execution (not portal-final / cancelled).
_OPEN_SHIPMENT_STATUSES = [
    TenantShipment.ShipmentStatus.CREATED,
    TenantShipment.ShipmentStatus.LOADED,
    TenantShipment.ShipmentStatus.IN_TRANSIT,
    TenantShipment.ShipmentStatus.AT_DELIVERY,
    TenantShipment.ShipmentStatus.POD_SUBMITTED,
    TenantShipment.ShipmentStatus.DELIVERED,
]

# Round-trip: outbound closed but backload not born yet (no open shipment rows).
_ROUND_TRIP_BACKLOAD_REOPEN = Q(trip_type__iexact='Round') & Q(
    shipments__shipment_status=TenantShipment.ShipmentStatus.CLOSED,
)


class DashboardBookingSelector:
    """
    Selects the single current booking and active shipment for a driver.

    Query strategy: driver-scoped bookings with at least one open leg, capped
    candidate scan, prefetched shipments sorted in Python (Outbound → Backload).
    """

    def select_current_driver_booking(
        self,
        driver: Any,
        *,
        tenant_schema: str = '',
    ) -> DriverBookingSelectionResult | None:
        _ = tenant_schema
        driver_pk = policy._driver_pk(driver)
        if driver_pk is None:
            return None
        allow_booking_bootstrap = self._auto_shipment_bootstrap_enabled()
        shipment_visibility_filter = Q(
            shipments__shipment_status__in=_OPEN_SHIPMENT_STATUSES,
        ) | _ROUND_TRIP_BACKLOAD_REOPEN
        if allow_booking_bootstrap:
            shipment_visibility_filter |= Q(shipments__isnull=True)

        shipments_qs = (
            TenantShipment.objects.select_related(
                'loading_address',
                'delivery_address',
                'client_account',
            )
            .defer('loading_address__extension', 'delivery_address__extension')
            .order_by('shipment_sequence', 'created_at')
        )
        bookings = (
            TenantBooking.objects.filter(
                Q(assigned_driver_id=driver_pk)
                | Q(booking_line_backload_driver_id=driver_pk)
                | Q(shipments__driver_id=driver_pk),
                booking_status=TenantBooking.Status.CONFIRMED,
            )
            .filter(shipment_visibility_filter)
            .distinct()
            .order_by(
                'booking_date',
                Coalesce('execution_date', 'booking_date'),
                'booking_sequence',
            )
            .select_related(
                'route',
                'route__origin_point',
                'route__destination_point',
                'loading_address',
                'delivery_address',
                'client_account',
            )
            .defer('loading_address__extension', 'delivery_address__extension')
            .prefetch_related(
                Prefetch('shipments', queryset=shipments_qs),
            )[:DASHBOARD_BOOKING_CANDIDATE_LIMIT]
        )

        for booking in bookings:
            shipments = list(booking.shipments.all())
            is_bootstrap_booking = allow_booking_bootstrap and not shipments
            is_backload_bootstrap = policy.is_round_trip_backload_bootstrap(
                driver,
                booking,
                shipments,
            )
            if not policy.booking_is_visible_to_driver(driver, booking, shipments):
                continue
            if shipments and policy.is_booking_fully_complete(
                shipments,
                booking=booking,
            ):
                continue

            ordered = policy.sorted_countable_shipments(shipments)
            active = policy.get_active_shipment_for_driver(driver, booking, ordered)
            if active is None and not (is_bootstrap_booking or is_backload_bootstrap):
                continue

            total, exec_completed, exec_pct = policy.booking_execution_progress_for_dashboard(
                booking,
                ordered,
            )
            _, biz_completed, biz_pct = policy.booking_business_progress_for_dashboard(
                booking,
                ordered,
            )
            stage = policy.derive_booking_execution_stage(
                booking, ordered, driver=driver
            )
            return DriverBookingSelectionResult(
                booking=booking,
                active_shipment=active,
                next_executable_shipment=policy.get_next_executable_shipment(
                    booking, ordered
                ),
                shipments=ordered,
                shipments_total=total,
                shipments_execution_completed=exec_completed,
                shipments_business_completed=biz_completed,
                execution_progress_percentage=exec_pct,
                business_progress_percentage=biz_pct,
                shipments_completed=exec_completed,
                progress_percentage=exec_pct,
                booking_execution_stage=stage,
                is_backload_bootstrap=is_backload_bootstrap,
            )

        return None

    @staticmethod
    def _auto_shipment_bootstrap_enabled() -> bool:
        """
        Booking-only bootstrap is allowed when at least one mobile action can
        auto-create a shipment from booking context.
        """
        try:
            return TenantOperationAction.objects.filter(
                status=TenantOperationAction.Status.ACTIVE,
                auto_shipment_post=True,
                mobile_visible=True,
                admin_only=False,
            ).exists()
        except (DatabaseOperationForbidden, OperationalError, ProgrammingError):
            return False

    def select_primary_booking(
        self,
        driver: Any,
        *,
        tenant_schema: str,
    ) -> Any | None:
        result = self.select_current_driver_booking(
            driver, tenant_schema=tenant_schema
        )
        return result.booking if result else None

    def select_active_shipment(
        self,
        booking: Any,
        *,
        tenant_schema: str,
        driver: Any,
    ) -> Any | None:
        _ = tenant_schema
        if booking is None:
            return None
        shipments = list(
            TenantShipment.objects.filter(booking_id=booking.pk).order_by(
                'shipment_sequence',
                'created_at',
            )
        )
        ordered = policy.sorted_countable_shipments(shipments)
        return policy.get_active_shipment_for_driver(driver, booking, ordered)


def select_current_driver_booking(
    driver: Any,
    *,
    tenant_schema: str = '',
) -> DriverBookingSelectionResult | None:
    return DashboardBookingSelector().select_current_driver_booking(
        driver,
        tenant_schema=tenant_schema,
    )
