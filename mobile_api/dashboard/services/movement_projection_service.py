"""
mobile_api/dashboard/services/movement_projection_service.py

Projects empty-move slices for ``current_empty_move`` on the dashboard.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.projections.movement_projection import (
    build_empty_move_card,
    build_movement_summary,
)
from mobile_api.dashboard.selectors.dashboard_movement_selector import (
    DashboardMovementSelector,
)


class MovementProjectionService:
    """
    Builds empty-move dashboard projections.

    Laden legs remain under booking/shipment orchestration.
    """

    def __init__(self, *, selector: DashboardMovementSelector | None = None) -> None:
        self._selector = selector or DashboardMovementSelector()

    def select_and_project_empty_move(
        self,
        driver: Any,
        *,
        tenant_schema: str = '',
        exclude_booking_id: Any | None = None,
        request: Any | None = None,
    ) -> tuple[DriverEmptyMoveSelectionResult | None, dict[str, Any], dict[str, Any]]:
        """
        Select active empty move and return ``(selection, card, summary)``.
        """
        selection = self._selector.select_current_empty_move(
            driver,
            tenant_schema=tenant_schema,
            exclude_booking_id=exclude_booking_id,
        )
        if selection is None:
            return None, {}, {}
        card = self.project_empty_move(selection=selection, request=request)
        summary = self.build_movement_summary(selection=selection)
        return selection, card, summary

    def project_empty_move(
        self,
        movement: Any | None = None,
        *,
        selection: DriverEmptyMoveSelectionResult | None = None,
        tenant_schema: str = '',
        driver: Any | None = None,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Project the empty-move card contract."""
        _ = (tenant_schema, driver)
        if selection is not None:
            return build_empty_move_card(selection=selection, request=request)
        return build_empty_move_card(movement, request=request)

    def build_movement_summary(
        self,
        movement: Any | None = None,
        *,
        selection: DriverEmptyMoveSelectionResult | None = None,
    ) -> dict[str, Any]:
        """Workflow state + metadata for dashboard orchestration."""
        return build_movement_summary(movement, selection=selection)

    def project_movement(
        self,
        movement: Any | None,
        *,
        tenant_schema: str,
        driver: Any,
        is_empty_move: bool = False,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Compat: only empty moves produce a card."""
        _ = (tenant_schema, driver)
        if not is_empty_move or movement is None:
            return {}
        return build_empty_move_card(movement, request=request)
