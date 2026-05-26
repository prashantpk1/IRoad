"""
mobile_api/dashboard/services/booking_projection_service.py

Projects booking-centric dashboard slices (active job, round-trip legs).
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.projections.booking_projection import (
    build_booking_card,
    build_booking_card_from_selection,
)
from mobile_api.dashboard.projections.shipment_projection import (
    build_active_shipment_slice,
)


class BookingProjectionService:
    """
    Builds booking + shipment card projections for the dashboard.

    Delegates field mapping to ``mobile_api.dashboard.projections`` modules;
    this service coordinates which projection runs for the current selection.
    """

    def project_booking(
        self,
        booking: Any | None,
        *,
        tenant_schema: str,
        driver: Any,
        selection: DriverBookingSelectionResult | None = None,
    ) -> dict[str, Any]:
        """Project the active booking for ``current_job`` assembly."""
        return build_booking_card(
            booking,
            tenant_schema=tenant_schema,
            driver=driver,
            selection=selection,
        )

    def project_booking_from_selection(
        self,
        selection: DriverBookingSelectionResult,
        *,
        tenant_schema: str = '',
    ) -> dict[str, Any]:
        return build_booking_card_from_selection(
            selection,
            tenant_schema=tenant_schema,
        )

    def project_shipment(
        self,
        shipment: Any | None,
        *,
        tenant_schema: str,
        driver: Any,
    ) -> dict[str, Any]:
        """Minimal active shipment slice for dashboard job card."""
        _ = (tenant_schema, driver)
        return build_active_shipment_slice(shipment)
