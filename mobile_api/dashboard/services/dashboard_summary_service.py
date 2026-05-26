"""
mobile_api/dashboard/services/dashboard_summary_service.py

Aggregates dashboard summary slices including workflow projection.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)
from mobile_api.dashboard.projections.pod_cod_projection import (
    build_pod_cod_summary_for_context,
)
from mobile_api.dashboard.projections.workflow_projection import (
    build_workflow_for_dashboard_context,
    build_workflow_from_booking_selection,
    build_workflow_from_empty_move_selection,
    build_workflow_projection,
)
from mobile_api.dashboard.services.dashboard_sync_metadata import (
    build_driver_dashboard_sync_metadata,
)
from mobile_api.dashboard.services.timeline_summary_service import (
    build_timeline_summary,
)


class DashboardSummaryService:
    """
    Cross-cutting dashboard aggregates: workflow, timeline, alerts, sync metadata.

    Workflow derivation delegates to ``operation_execution`` / ``operation_runtime``
    via ``workflow_projection`` — no duplicated Action Master rules.
    """

    def build_workflow(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Build the ``workflow`` block (one ``get_allowed_actions`` call via engine)."""
        return build_workflow_for_dashboard_context(context, request=request)

    def build_workflow_for_job(
        self,
        booking_selection: DriverBookingSelectionResult | None,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        if booking_selection is None:
            return build_workflow_projection()
        return build_workflow_from_booking_selection(
            booking_selection,
            request=request,
        )

    def build_workflow_for_empty_move(
        self,
        empty_move_selection: DriverEmptyMoveSelectionResult | None,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        if empty_move_selection is None:
            return build_workflow_projection()
        return build_workflow_from_empty_move_selection(
            empty_move_selection,
            request=request,
        )

    def build_summary(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Internal summary bag (timeline + alerts); workflow exposed at top level."""
        return {
            'timeline_summary': self.build_timeline_summary(context),
            'alerts': self.build_alerts(context),
        }

    def build_timeline_summary(self, context: DriverDashboardContext) -> dict[str, Any]:
        return build_timeline_summary(context)

    def build_alerts(self, context: DriverDashboardContext) -> dict[str, Any]:
        """Derive alert chips from POD/COD flags (no extra Action Master scan)."""
        pod = context.pod_cod_projection or {}
        items = []

        def _add(code: str, severity: str = 'warning') -> None:
            items.append({'code': code, 'severity': severity})

        if pod.get('delivery_blocked'):
            _add('delivery_blocked', 'error')
        if pod.get('pod_pending'):
            _add('pod_pending')
        if pod.get('hard_pod_pending'):
            _add('hard_pod_pending')
        if pod.get('cod_pending'):
            _add('cod_pending')
        if pod.get('treasury_pending'):
            _add('treasury_pending')
        if pod.get('pod_compliant'):
            _add('pod_compliant', 'info')

        return {'count': len(items), 'items': items}

    def build_sync_metadata(self, context: DriverDashboardContext) -> dict[str, Any]:
        """Offline sync / replay metadata for the mobile client."""
        return build_driver_dashboard_sync_metadata(context)

    def populate_context_workflow(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None = None,
    ) -> DriverDashboardContext:
        context.workflow_projection = self.build_workflow(context, request=request)
        return context
