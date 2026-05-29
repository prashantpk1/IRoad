"""
mobile_api/dashboard/dto/dashboard_response_builder.py

Assembles the canonical driver dashboard API payload from orchestration context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.projections.workflow_projection import _EMPTY_WORKFLOW
from mobile_api.dashboard.selectors.pod_cod_policy import derive_pod_cod_flags

_EMPTY_TIMELINE: dict[str, Any] = {
    'scope': '',
    'preview_limit': 20,
    'recent_count': 0,
    'recent_events': [],
    'has_more': False,
}


class DashboardApiPayload(TypedDict, total=False):
    """Typed contract for dashboard ``data``."""

    current_job: dict[str, Any]
    active_job: dict[str, Any]
    current_empty_move: dict[str, Any]
    workflow: dict[str, Any]
    pod_cod_summary: dict[str, Any]
    timeline_summary: dict[str, Any]
    alerts: dict[str, Any]
    sync_metadata: dict[str, Any]


@dataclass
class DashboardResponseBuilder:
    """Maps ``DriverDashboardContext`` → API-ready ``DashboardApiPayload``."""

    def build(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None = None,
    ) -> DashboardApiPayload:
        summary = context.summary or {}
        return DashboardApiPayload(
            current_job=self._build_current_job(context),
            active_job=self._build_active_job(context, request=request),
            current_empty_move=self._build_current_empty_move(context),
            workflow=self._build_workflow(context),
            pod_cod_summary=self._build_pod_cod_summary(context),
            timeline_summary=summary.get('timeline_summary')
            or self._build_timeline_summary(context),
            alerts=summary.get('alerts') or self._build_alerts(context),
            sync_metadata=self._build_sync_metadata(context),
        )

    def _build_current_job(self, context: DriverDashboardContext) -> dict[str, Any]:
        return dict(context.booking_projection or {})

    def _build_active_job(
        self,
        context: DriverDashboardContext,
        *,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """Top-level job pointer + route/addresses (Postman + mobile home screen)."""
        from mobile_api.dashboard.projections.job_location_dashboard import (
            build_dashboard_active_job,
        )

        return build_dashboard_active_job(
            shipment=context.active_shipment,
            booking=context.active_booking,
            movement=context.active_empty_movement,
            request=request,
        )

    def _build_current_empty_move(
        self, context: DriverDashboardContext
    ) -> dict[str, Any]:
        return dict(context.movement_projection or {})

    def _build_workflow(self, context: DriverDashboardContext) -> dict[str, Any]:
        workflow = context.workflow_projection
        if workflow:
            return dict(workflow)
        return dict(_EMPTY_WORKFLOW)

    def _build_pod_cod_summary(self, context: DriverDashboardContext) -> dict[str, Any]:
        pod = context.pod_cod_projection
        if pod:
            return dict(pod)
        if context.active_shipment is not None:
            return dict(
                derive_pod_cod_flags(
                    context.active_shipment,
                    driver=context.driver,
                )
            )
        return {
            'pod_pending': False,
            'pod_compliant': False,
            'hard_pod_pending': False,
            'cod_pending': False,
            'cod_collected': False,
            'treasury_pending': False,
            'delivery_blocked': False,
        }

    def _build_timeline_summary(self, context: DriverDashboardContext) -> dict[str, Any]:
        summary = context.summary or {}
        timeline = summary.get('timeline_summary')
        if timeline:
            return dict(timeline)
        return dict(_EMPTY_TIMELINE)

    def _build_alerts(self, context: DriverDashboardContext) -> dict[str, Any]:
        summary = context.summary or {}
        alerts = summary.get('alerts')
        if alerts:
            return dict(alerts)
        return {'count': 0, 'items': []}

    def _build_sync_metadata(self, context: DriverDashboardContext) -> dict[str, Any]:
        return dict(context.sync_metadata or {})
