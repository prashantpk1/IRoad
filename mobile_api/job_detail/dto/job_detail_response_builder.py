"""
mobile_api/job_detail/dto/job_detail_response_builder.py

Maps ``JobDetailContext`` → unified Job Detail API ``data`` contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
    apply_hard_pod_workflow_overlay,
)
from mobile_api.utils.next_action_hint_builder import build_next_action_hint

_EMPTY_JOB: dict[str, Any] = {
    'job_type': '',
    'job_id': '',
    'job_no': '',
    'entity_type': '',
}


class JobDetailApiPayload(TypedDict, total=False):
    """
    Unified Job Detail ``data`` envelope sections.

    Contract (stable top-level keys):
      - job
      - workflow
      - timeline
      - pod_cod
      - round_trip
      - alerts
      - sync_metadata
      - operational_issues (shipment advisory)
    """

    job: dict[str, Any]
    workflow: dict[str, Any]
    timeline: dict[str, Any]
    pod_cod: dict[str, Any]
    round_trip: dict[str, Any]
    alerts: dict[str, Any]
    sync_metadata: dict[str, Any]
    operational_issues: list[dict[str, Any]]
    unresolved_issue_count: int
    blocking_recommendation: bool
    next_action_hint: dict[str, Any]


@dataclass
class JobDetailResponseBuilder:
    """Assembles the canonical Job Detail API payload from orchestration context."""

    def build(self, context: JobDetailContext) -> JobDetailApiPayload:
        """
        Map context projections to the outward contract.

        TODO: enforce empty-move omission rules for ``pod_cod`` / ``round_trip``.
        """
        visibility = self._build_operational_issues_visibility(context)
        workflow = self._build_workflow(context)
        pod_cod = self._build_pod_cod(context)
        workflow = apply_hard_pod_workflow_overlay(workflow, pod_cod)
        timeline = self._build_timeline(context)
        workflow = self._attach_booking_timeline_to_workflow(
            context,
            workflow,
            timeline,
        )

        order_type = ''
        try:
            order_type = (
                context.shipment.order_type
                if hasattr(context, 'shipment') and context.shipment
                else ''
            )
        except Exception:
            order_type = ''

        next_hint = build_next_action_hint(
            workflow=workflow,
            pod_cod=pod_cod,
            action_code=None,
            order_type=order_type,
            shipment=getattr(context, 'shipment', None),
            booking=getattr(context, 'booking', None),
            driver=getattr(context, 'driver', None),
        )

        return JobDetailApiPayload(
            job=self._build_job(context),
            workflow=workflow,
            timeline=timeline,
            pod_cod=pod_cod,
            round_trip=self._build_round_trip(context),
            alerts=self._build_alerts(context),
            sync_metadata=self._build_sync_metadata(context),
            operational_issues=list(visibility.get('operational_issues') or []),
            unresolved_issue_count=int(visibility.get('unresolved_issue_count') or 0),
            blocking_recommendation=bool(visibility.get('blocking_recommendation')),
            next_action_hint=next_hint,
        )

    def _build_job(self, context: JobDetailContext) -> dict[str, Any]:
        if context.job_header:
            return dict(context.job_header)
        return dict(_EMPTY_JOB)

    def _build_workflow(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.workflow or {})

    def _build_timeline(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.timeline or {})

    @staticmethod
    def _attach_booking_timeline_to_workflow(
        context: JobDetailContext,
        workflow: dict[str, Any],
        timeline: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Booking-scoped jobs: mirror full timeline steps on workflow for clients
        that render the stepper from ``workflow`` instead of ``timeline``.
        """
        if context.job_type != 'booking':
            return workflow
        preview = list(timeline.get('timeline_preview') or [])
        if not preview:
            return workflow
        out = dict(workflow or {})
        out['timeline_preview'] = preview
        out['timeline_step_count'] = len(preview)
        return out

    def _build_pod_cod(self, context: JobDetailContext) -> dict[str, Any]:
        # TODO: return {} for movement jobs at assembly time if not already omitted upstream.
        if context.job_type == 'movement':
            return {}
        return dict(context.pod_cod or {})

    def _build_round_trip(self, context: JobDetailContext) -> dict[str, Any]:
        if context.job_type == 'movement':
            return {}
        return dict(context.round_trip or {})

    def _build_alerts(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.alerts or {})

    def _build_sync_metadata(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.sync_metadata or {})

    @staticmethod
    def _build_operational_issues_visibility(context: JobDetailContext) -> dict[str, Any]:
        cached = (context.resolver_meta or {}).get('operational_issues_visibility')
        if isinstance(cached, dict):
            return cached
        if context.job_type != 'shipment':
            return {
                'operational_issues': [],
                'unresolved_issue_count': 0,
                'blocking_recommendation': False,
            }
        from mobile_api.job_detail.projections.job_detail_projection_builder import (
            build_operational_issues_visibility,
        )

        return build_operational_issues_visibility(context)
