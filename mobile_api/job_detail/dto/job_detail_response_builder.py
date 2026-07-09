"""
mobile_api/job_detail/dto/job_detail_response_builder.py

Maps ``JobDetailContext`` → unified Job Detail API ``data`` contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.services.job_detail_navigation_reconciler import (
    apply_pod_mobile_cta_contract,
    finalize_job_detail_workflow_cta,
    reconcile_job_detail_cta,
)
from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
    apply_hard_pod_workflow_overlay,
    enrich_pod_cod_hard_copy_gate,
    finalize_pod_cod_hard_copy_navigation,
)
from mobile_api.helpers.action_navigation_metadata import (
    enrich_workflow_pod_navigation,
    finalize_timeline_preview_navigation,
    sync_workflow_primary_from_next_hint,
)
from mobile_api.job_detail.projections.movement_workflow_timeline_sync import (
    attach_timeline_preview_to_workflow,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    sort_timeline_display_order,
)
from mobile_api.helpers.open_job_pointer import (
    build_job_navigation_block,
    build_open_job_pointer,
)
from mobile_api.utils.next_action_hint_builder import (
    align_next_action_hint_with_workflow,
    build_next_action_hint,
)

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
    support_actions: list[dict[str, Any]]
    unresolved_issue_count: int
    blocking_recommendation: bool
    next_action_hint: dict[str, Any]
    open_job: dict[str, Any]
    navigation: dict[str, Any]


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
        evidence = dict(
            ((context.reconciliation or {}).get('pod_cod') or {}).get('log_evidence') or {}
        )
        if context.job_type in {'shipment', 'movement', 'booking'}:
            workflow = enrich_workflow_pod_navigation(
                workflow,
                shipment=getattr(context, 'shipment', None),
                tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
                log_evidence=evidence,
            )
        pod_cod = enrich_pod_cod_hard_copy_gate(pod_cod)
        pod_cod = finalize_pod_cod_hard_copy_navigation(pod_cod)
        timeline = self._build_timeline(context)

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
            movement=getattr(context, 'movement', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        next_hint = align_next_action_hint_with_workflow(
            next_hint,
            workflow,
            pod_cod,
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
            shipment=getattr(context, 'shipment', None),
            booking=getattr(context, 'booking', None),
            driver=getattr(context, 'driver', None),
        )
        workflow = sync_workflow_primary_from_next_hint(
            workflow,
            next_hint,
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        if context.job_type in {'shipment', 'movement', 'booking'}:
            workflow = enrich_workflow_pod_navigation(
                workflow,
                shipment=getattr(context, 'shipment', None),
                tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
                log_evidence=evidence,
            )
        timeline = self._finalize_timeline_navigation(
            context,
            timeline,
            pod_cod=pod_cod,
        )
        workflow, next_hint = reconcile_job_detail_cta(
            workflow,
            next_hint,
            timeline=timeline,
            pod_cod=pod_cod,
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        workflow = sync_workflow_primary_from_next_hint(
            workflow,
            next_hint,
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        if context.job_type in {'shipment', 'movement', 'booking'}:
            workflow = enrich_workflow_pod_navigation(
                workflow,
                shipment=getattr(context, 'shipment', None),
                tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
                log_evidence=evidence,
            )
        next_hint = align_next_action_hint_with_workflow(
            next_hint,
            workflow,
            pod_cod,
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
            shipment=getattr(context, 'shipment', None),
            booking=getattr(context, 'booking', None),
            driver=getattr(context, 'driver', None),
        )
        workflow = self._attach_booking_timeline_to_workflow(
            context,
            workflow,
            timeline,
        )
        workflow, next_hint = reconcile_job_detail_cta(
            workflow,
            next_hint,
            timeline=timeline,
            pod_cod=pod_cod,
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        workflow = sync_workflow_primary_from_next_hint(
            workflow,
            next_hint,
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        if context.job_type in {'shipment', 'movement', 'booking'}:
            workflow = enrich_workflow_pod_navigation(
                workflow,
                shipment=getattr(context, 'shipment', None),
                tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
                log_evidence=evidence,
            )
        next_hint = apply_pod_mobile_cta_contract(next_hint)
        workflow, next_hint = finalize_job_detail_workflow_cta(
            workflow,
            next_hint,
            timeline=timeline,
            pod_cod=pod_cod,
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        from mobile_api.helpers.hard_copy_workflow_gate import (
            enforce_job_detail_pod_digital_first,
            hard_copy_step_due,
            scrub_premature_hard_pod_job_detail_payload,
        )

        workflow, next_hint = enforce_job_detail_pod_digital_first(
            workflow,
            next_hint,
            pod_cod=pod_cod,
        )
        workflow, pod_cod, next_hint = scrub_premature_hard_pod_job_detail_payload(
            workflow=workflow,
            pod_cod=pod_cod,
            next_hint=next_hint,
            timeline=timeline,
        )
        shipment_obj = getattr(context, 'shipment', None)
        unloading_completed_logged = True
        if shipment_obj is not None:
            from iroad_tenants.operation_runtime.shipment_execution_stage import (
                shipment_unloading_completed_done,
            )

            unloading_completed_logged = shipment_unloading_completed_done(shipment_obj)
        if hard_copy_step_due(pod_cod) and unloading_completed_logged:
            workflow = apply_hard_pod_workflow_overlay(workflow, pod_cod)
        timeline = dict(timeline or {})
        if workflow.get('timeline_preview'):
            timeline['timeline_preview'] = list(workflow.get('timeline_preview') or [])

        support_actions = self._build_support_actions(context)
        job = self._build_job(context)
        open_job = self._build_open_job(job)
        navigation = self._build_navigation(context, job=job)

        return JobDetailApiPayload(
            job=job,
            workflow=workflow,
            timeline=timeline,
            pod_cod=pod_cod,
            round_trip=self._build_round_trip(context),
            alerts=self._build_alerts(context),
            sync_metadata=self._build_sync_metadata(context),
            operational_issues=list(visibility.get('operational_issues') or []),
            support_actions=support_actions,
            unresolved_issue_count=int(visibility.get('unresolved_issue_count') or 0),
            blocking_recommendation=bool(visibility.get('blocking_recommendation')),
            next_action_hint=next_hint,
            open_job=open_job,
            navigation=navigation,
        )

    def _build_job(self, context: JobDetailContext) -> dict[str, Any]:
        if context.job_header:
            return dict(context.job_header)
        return dict(_EMPTY_JOB)

    @staticmethod
    def _build_open_job(job: dict[str, Any]) -> dict[str, Any]:
        return build_open_job_pointer(
            job_type=str(job.get('job_type') or ''),
            job_id=str(job.get('job_id') or ''),
            job_no=str(job.get('job_no') or ''),
            booking_item_type=str(job.get('booking_item_type') or ''),
            backload_bootstrap_pending=bool(job.get('backload_bootstrap_pending')),
        )

    @staticmethod
    def _build_navigation(
        context: JobDetailContext,
        *,
        job: dict[str, Any],
    ) -> dict[str, Any]:
        job_type = str(job.get('job_type') or context.job_type or '').strip()
        job_id = str(job.get('job_id') or context.job_id or '').strip()
        if not job_type or not job_id:
            return {}

        return build_job_navigation_block(
            job_type=job_type,
            job_id=job_id,
            resolver_meta=dict(context.resolver_meta or {}),
        )

    def _build_workflow(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.workflow or {})

    def _build_timeline(self, context: JobDetailContext) -> dict[str, Any]:
        return dict(context.timeline or {})

    def _finalize_timeline_navigation(
        self,
        context: JobDetailContext,
        timeline: dict[str, Any],
        *,
        pod_cod: dict[str, Any],
    ) -> dict[str, Any]:
        if context.job_type not in {'shipment', 'movement', 'booking'}:
            return timeline
        out = dict(timeline or {})
        evidence = dict(pod_cod.get('log_evidence') or {})
        preview = finalize_timeline_preview_navigation(
            list(out.get('timeline_preview') or []),
            shipment=getattr(context, 'shipment', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
            log_evidence=evidence,
        )
        if preview:
            out['timeline_preview'] = sort_timeline_display_order(preview)
        return out

    @staticmethod
    def _attach_booking_timeline_to_workflow(
        context: JobDetailContext,
        workflow: dict[str, Any],
        timeline: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Mirror full timeline steps on workflow for clients that render the stepper
        from ``workflow`` instead of ``timeline`` (booking + shipment jobs).
        """
        preview = list(timeline.get('timeline_preview') or [])
        if not preview:
            return workflow
        if context.job_type not in {'booking', 'shipment', 'movement'}:
            return workflow
        return attach_timeline_preview_to_workflow(
            workflow,
            timeline,
            job_type=context.job_type,
        )

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

    def _build_support_actions(self, context: JobDetailContext) -> list[dict[str, Any]]:
        if context.job_type not in {'shipment', 'movement', 'booking'}:
            return []
        from mobile_api.job_detail.projections.support_actions_projection import (
            build_job_support_actions,
        )

        return build_job_support_actions(
            request=getattr(context, 'request', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
            shipment=getattr(context, 'shipment', None),
            movement=getattr(context, 'movement', None),
        )

    @staticmethod
    def _build_operational_issues_visibility(context: JobDetailContext) -> dict[str, Any]:
        cached = (context.resolver_meta or {}).get('operational_issues_visibility')
        if isinstance(cached, dict):
            return cached
        if context.job_type not in {'shipment', 'movement'}:
            return {
                'operational_issues': [],
                'unresolved_issue_count': 0,
                'blocking_recommendation': False,
            }
        from mobile_api.job_detail.projections.job_detail_projection_builder import (
            build_operational_issues_visibility,
        )

        return build_operational_issues_visibility(context)
