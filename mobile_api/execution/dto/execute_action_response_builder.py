"""
mobile_api/execution/dto/execute_action_response_builder.py

Maps ``ExecuteActionContext`` → unified Execute Action API ``data`` contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.helpers.action_navigation_metadata import enrich_workflow_pod_navigation
from mobile_api.job_detail.services.hard_pod_workflow_overlay import (
    apply_hard_pod_workflow_overlay,
    enrich_pod_cod_hard_copy_gate,
    finalize_pod_cod_hard_copy_navigation,
)
from mobile_api.job_detail.projections.movement_workflow_timeline_sync import (
    attach_timeline_preview_to_workflow,
)
from mobile_api.helpers.open_job_pointer import (
    build_job_navigation_block,
    build_open_job_pointer,
)
from mobile_api.utils.next_action_hint_builder import (
    align_next_action_hint_with_workflow,
    build_next_action_hint,
    resolve_round_trip_continuation_open_job,
)

_EMPTY_TIMELINE_PREVIEW: dict[str, Any] = {
    'scope': '',
    'timeline_preview': [],
    'timeline_cursor': '',
    'has_more': False,
}


class ExecuteActionApiPayload(TypedDict, total=False):
    """
    Unified Execute Action ``data`` envelope.

    Contract:
      - execution
      - workflow (includes allowed_actions, next_action, primary_action)
      - pod_cod (shipment only)
      - timeline_preview (Job Detail timeline projection subset)
      - sync_metadata
      - alerts
    """

    execution: dict[str, Any]
    workflow: dict[str, Any]
    pod_cod: dict[str, Any]
    timeline_preview: dict[str, Any]
    sync_metadata: dict[str, Any]
    alerts: dict[str, Any]
    next_action_hint: dict[str, Any]
    job: dict[str, Any]
    open_job: dict[str, Any]
    navigation: dict[str, Any]


@dataclass
class ExecuteActionResponseBuilder:
    """Assembles the canonical Execute Action API payload from orchestration context."""

    def build(self, context: ExecuteActionContext) -> ExecuteActionApiPayload:
        workflow = self._build_workflow(context)
        pod_cod = self._build_pod_cod(context)
        evidence = dict(
            ((context.reconciliation or {}).get('pod_cod') or {}).get('log_evidence') or {}
        )
        if context.job_type in {'shipment', 'movement', 'booking'}:
            workflow = enrich_workflow_pod_navigation(
                workflow,
                shipment=getattr(context, 'shipment', None),
                tenant_schema=(context.tenant_schema or '').strip(),
                log_evidence=evidence,
            )
        pod_cod = enrich_pod_cod_hard_copy_gate(pod_cod)
        pod_cod = finalize_pod_cod_hard_copy_navigation(pod_cod)
        execution = self._build_execution(context)

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
            action_code=context.action_code,
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
        from mobile_api.helpers.hard_copy_workflow_gate import coerce_digital_pod_capture_row

        next_hint = coerce_digital_pod_capture_row(next_hint, pod_cod=pod_cod)
        if (
            next_hint.get('booking_continues')
            and (
                next_hint.get('job_closed')
                or next_hint.get('leg_completed')
            )
        ):
            workflow = {
                'current_stage': '',
                'next_action': {},
                'primary_action': {},
                'allowed_actions': [],
                'workflow_source': workflow.get('workflow_source', ''),
                'workflow_metadata': {
                    'context_label': (
                        'Outbound leg complete — open booking job for backload preshipment.'
                    ),
                },
            }
            pod_cod = {}
        elif next_hint.get('job_closed'):
            pod_cod = finalize_pod_cod_hard_copy_navigation(pod_cod)
        execution['job_closed'] = next_hint.get('job_closed', False)
        execution['next_step'] = next_hint.get('action', 'refresh_job_detail')

        timeline = dict(context.timeline or {})
        workflow = attach_timeline_preview_to_workflow(
            workflow,
            timeline,
            job_type=context.job_type,
        )
        from mobile_api.helpers.hard_copy_workflow_gate import (
            enforce_job_detail_pod_digital_first,
            hard_copy_step_due,
        )

        workflow, next_hint = enforce_job_detail_pod_digital_first(
            workflow,
            next_hint,
            pod_cod=pod_cod,
        )
        if hard_copy_step_due(pod_cod):
            workflow = apply_hard_pod_workflow_overlay(workflow, pod_cod)

        job = self._build_job(context)
        open_job = self._build_open_job(context, job=job, next_hint=next_hint)
        navigation = self._build_navigation(context, job=job, open_job=open_job)

        return ExecuteActionApiPayload(
            execution=execution,
            workflow=workflow,
            job=job,
            pod_cod=pod_cod,
            timeline_preview=self._build_timeline_preview(context),
            sync_metadata=self._build_sync_metadata(context),
            alerts=self._build_alerts(context),
            next_action_hint=next_hint,
            open_job=open_job,
            navigation=navigation,
        )

    def _build_execution(self, context: ExecuteActionContext) -> dict[str, Any]:
        action_log = context.action_log
        log_id = None
        log_no = ''
        log_date = None
        if action_log is not None:
            log_id = getattr(action_log, 'log_id', None) or getattr(action_log, 'pk', None)
            log_no = str(getattr(action_log, 'log_no', '') or '')
            log_date = getattr(action_log, 'log_date', None)

        replayed = bool(context.idempotent_replay or context.reused_existing)
        executed_at = None
        if log_date is not None:
            executed_at = (
                log_date.isoformat()
                if hasattr(log_date, 'isoformat')
                else str(log_date)
            )

        meta = dict(context.resolver_meta or {})
        booking_item_type = ''
        if context.booking is not None:
            from mobile_api.job_detail.helpers.booking_job_context import (
                resolve_pending_booking_item_type,
            )

            booking_item_type = resolve_pending_booking_item_type(
                context.booking,
                driver=context.driver,
            )

        return {
            'job_type': context.job_type,
            'job_id': context.job_id,
            'action_code': context.action_code,
            'booking_item_type': booking_item_type,
            'backload_booking_redirect': bool(meta.get('backload_booking_redirect')),
            'redirected_from_shipment_id': str(
                meta.get('redirected_from_shipment_id') or ''
            ).strip(),
            'shipment_id': str(getattr(action_log, 'shipment_id', '') or ''),
            'movement_id': str(getattr(action_log, 'truck_movement_id', '') or ''),
            'reused_existing': bool(context.reused_existing),
            'idempotent_replay': bool(context.idempotent_replay),
            'replayed': replayed,
            'original_action_log_id': str(log_id) if log_id is not None else None,
            'executed_at': executed_at,
            'action_log_id': str(log_id) if log_id is not None else None,
            'log_no': log_no,
            'log_date': executed_at,
            'idempotency_key': (context.idempotency_key or '').strip(),
        }

    def _build_workflow(self, context: ExecuteActionContext) -> dict[str, Any]:
        workflow = dict(context.workflow or {})
        if not workflow:
            return {
                'current_stage': '',
                'next_action': {},
                'primary_action': {},
                'allowed_actions': [],
            }
        return workflow

    def _build_pod_cod(self, context: ExecuteActionContext) -> dict[str, Any]:
        if context.job_type == 'movement':
            return {}
        return dict(context.pod_cod or {})

    def _build_job(self, context: ExecuteActionContext) -> dict[str, Any]:
        """Job header for shipment, booking, and movement execute responses."""
        job = dict(context.job or {})
        if job and context.job_type != 'movement':
            return job
        from mobile_api.execution.services.execution_context_adapter import (
            to_job_detail_context,
        )
        from mobile_api.job_detail.projections.job_header_projection import (
            build_job_header,
        )

        jd_ctx = to_job_detail_context(context)
        return build_job_header(jd_ctx, request=None)

    @staticmethod
    def _build_open_job(
        context: ExecuteActionContext,
        *,
        job: dict[str, Any],
        next_hint: dict[str, Any],
    ) -> dict[str, Any]:
        hint_open = dict(next_hint.get('open_job') or {})
        if hint_open.get('job_type') and hint_open.get('job_id'):
            return build_open_job_pointer(
                job_type=str(hint_open.get('job_type') or ''),
                job_id=str(hint_open.get('job_id') or ''),
                job_no=str(hint_open.get('job_no') or job.get('job_no') or ''),
                booking_item_type=str(
                    hint_open.get('booking_item_type')
                    or job.get('booking_item_type')
                    or ''
                ),
                backload_bootstrap_pending=bool(
                    hint_open.get('backload_bootstrap_pending')
                    or job.get('backload_bootstrap_pending')
                ),
            )
        continuation = resolve_round_trip_continuation_open_job(
            context.booking,
            driver=context.driver,
        )
        if continuation:
            return build_open_job_pointer(
                job_type=str(continuation.get('job_type') or ''),
                job_id=str(continuation.get('job_id') or ''),
                job_no=str(continuation.get('job_no') or job.get('job_no') or ''),
                booking_item_type=str(continuation.get('booking_item_type') or ''),
                backload_bootstrap_pending=bool(
                    continuation.get('backload_bootstrap_pending')
                ),
            )
        return build_open_job_pointer(
            job_type=str(job.get('job_type') or context.job_type or ''),
            job_id=str(job.get('job_id') or context.job_id or ''),
            job_no=str(job.get('job_no') or ''),
            booking_item_type=str(job.get('booking_item_type') or ''),
            backload_bootstrap_pending=bool(job.get('backload_bootstrap_pending')),
        )

    @staticmethod
    def _build_navigation(
        context: ExecuteActionContext,
        *,
        job: dict[str, Any],
        open_job: dict[str, Any],
    ) -> dict[str, Any]:
        if open_job.get('job_type') and open_job.get('job_id'):
            meta = dict(context.resolver_meta or {})
            if open_job.get('backload_bootstrap_pending'):
                meta.setdefault('backload_booking_redirect', True)
            return build_job_navigation_block(
                job_type=str(open_job.get('job_type') or ''),
                job_id=str(open_job.get('job_id') or ''),
                resolver_meta=meta,
            )
        return build_job_navigation_block(
            job_type=str(job.get('job_type') or context.job_type or ''),
            job_id=str(job.get('job_id') or context.job_id or ''),
            resolver_meta=dict(context.resolver_meta or {}),
        )

    def _build_timeline_preview(self, context: ExecuteActionContext) -> dict[str, Any]:
        """Expose Job Detail ``timeline`` bundle as ``timeline_preview`` (no duplicate logic)."""
        timeline = dict(context.timeline or {})
        if not timeline:
            out = dict(_EMPTY_TIMELINE_PREVIEW)
            out['scope'] = context.job_type
            return out
        return {
            'scope': str(timeline.get('scope') or context.job_type),
            'timeline_preview': list(timeline.get('timeline_preview') or []),
            'timeline_cursor': str(timeline.get('timeline_cursor') or ''),
            'has_more': bool(timeline.get('has_more', False)),
            'preview_limit': timeline.get('preview_limit'),
        }

    def _build_sync_metadata(self, context: ExecuteActionContext) -> dict[str, Any]:
        return dict(context.sync_metadata or {})

    def _build_alerts(self, context: ExecuteActionContext) -> dict[str, Any]:
        return dict(context.alerts or {})
