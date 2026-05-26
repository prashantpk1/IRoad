"""
mobile_api/dashboard/selectors/dashboard_movement_selector.py

Empty-move selection for the unified driver dashboard.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from tenant_workspace.models import TenantTruckMovementLog

from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.polling_constants import (
    DASHBOARD_MOVEMENT_CANDIDATE_LIMIT,
    DASHBOARD_MOVEMENT_LOOKBACK_DAYS,
)
from mobile_api.dashboard.selectors import movement_selection_policy as policy


class DashboardMovementSelector:
    """Selects the driver's current empty truck movement (bounded queryset)."""

    def select_current_empty_move(
        self,
        driver: Any,
        *,
        tenant_schema: str = '',
        exclude_booking_id: Any | None = None,
    ) -> DriverEmptyMoveSelectionResult | None:
        _ = tenant_schema
        driver_pk = policy.driver_pk_value(driver)
        if driver_pk is None:
            return None

        cutoff = timezone.now().date() - timedelta(days=DASHBOARD_MOVEMENT_LOOKBACK_DAYS)

        movements_qs = (
            TenantTruckMovementLog.objects.filter(
                driver_id=driver_pk,
                shipment_id__isnull=True,
                movement_date__gte=cutoff,
            )
            .exclude(
                status__in=(
                    TenantTruckMovementLog.Status.COMPLETED,
                    TenantTruckMovementLog.Status.CANCELLED,
                ),
            )
            .exclude(movement_source__iexact='loaded')
            .order_by('movement_date', 'movement_sequence', 'created_at')[
                :DASHBOARD_MOVEMENT_CANDIDATE_LIMIT
            ]
        )

        movement = policy.select_active_empty_move_from_list(
            driver,
            movements_qs,
            exclude_booking_id=exclude_booking_id,
        )
        if movement is None:
            return None

        return self._result_from_movement(movement)

    def select_empty_move(
        self,
        driver: Any,
        *,
        tenant_schema: str,
        exclude_booking_id: Any | None = None,
    ) -> Any | None:
        result = self.select_current_empty_move(
            driver,
            tenant_schema=tenant_schema,
            exclude_booking_id=exclude_booking_id,
        )
        return result.movement if result else None

    def select_movement_for_shipment(
        self,
        shipment: Any,
        *,
        tenant_schema: str,
        driver: Any,
    ) -> Any | None:
        _ = (shipment, tenant_schema, driver)
        return None

    @staticmethod
    def _result_from_movement(movement: Any) -> DriverEmptyMoveSelectionResult:
        stage = policy.movement_execution_stage(movement)
        return DriverEmptyMoveSelectionResult(
            movement=movement,
            movement_stage=stage,
            movement_status=str(getattr(movement, 'status', '') or ''),
            progress_percentage=policy.movement_progress_percentage(movement),
            summary=policy.build_movement_summary(movement),
        )


def select_current_driver_empty_move(
    driver: Any,
    *,
    tenant_schema: str = '',
    exclude_booking_id: Any | None = None,
) -> DriverEmptyMoveSelectionResult | None:
    return DashboardMovementSelector().select_current_empty_move(
        driver,
        tenant_schema=tenant_schema,
        exclude_booking_id=exclude_booking_id,
    )
