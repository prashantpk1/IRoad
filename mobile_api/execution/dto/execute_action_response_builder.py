"""
mobile_api/execution/dto/execute_action_response_builder.py

Maps ``ExecuteActionContext`` → unified Execute Action API ``data`` contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.utils.next_action_hint_builder import build_next_action_hint

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


@dataclass
class ExecuteActionResponseBuilder:
    """Assembles the canonical Execute Action API payload from orchestration context."""

    def build(self, context: ExecuteActionContext) -> ExecuteActionApiPayload:
        workflow = self._build_workflow(context)
        pod_cod = self._build_pod_cod(context)
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
        )
        execution['job_closed'] = next_hint.get('job_closed', False)
        execution['next_step'] = next_hint.get('action', 'refresh_job_detail')

        return ExecuteActionApiPayload(
            execution=execution,
            workflow=workflow,
            pod_cod=pod_cod,
            timeline_preview=self._build_timeline_preview(context),
            sync_metadata=self._build_sync_metadata(context),
            alerts=self._build_alerts(context),
            next_action_hint=next_hint,
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

        return {
            'job_type': context.job_type,
            'job_id': context.job_id,
            'action_code': context.action_code,
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
