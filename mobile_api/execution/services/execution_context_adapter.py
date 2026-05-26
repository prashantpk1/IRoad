"""
mobile_api/execution/services/execution_context_adapter.py

Bridge ``ExecuteActionContext`` ↔ ``JobDetailContext`` for read-only job_detail primitives.
"""
from __future__ import annotations

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext


def to_job_detail_context(context: ExecuteActionContext) -> JobDetailContext:
    """
    Build a Job Detail orchestration context sharing the same resolved entities.

    Used for projection cache, reconciliation, and workflow (log-primary overlays).
    """
    return JobDetailContext(
        driver=context.driver,
        tenant_schema=context.tenant_schema,
        user_id=context.user_id,
        job_type=context.job_type,
        job_id=context.job_id,
        shipment=context.shipment,
        movement=context.movement,
        booking=context.booking,
        resolver_meta=dict(context.resolver_meta or {}),
        projection_cache=context.projection_cache,
        reconciliation=dict(context.reconciliation or {}),
        workflow=dict(context.workflow or {}),
        pod_cod=dict(context.pod_cod or {}),
        round_trip=dict(context.round_trip or {}),
        timeline=dict(context.timeline or {}),
        alerts=dict(context.alerts or {}),
        sync_metadata=dict(context.sync_metadata or {}),
        latest_action_log_id=getattr(context, 'latest_action_log_id', '') or '',
    )


def sync_from_job_detail(
    execute_context: ExecuteActionContext,
    job_detail_context: JobDetailContext,
) -> None:
    """Copy reconciliation / projection fields back to execute context."""
    execute_context.projection_cache = job_detail_context.projection_cache
    execute_context.reconciliation = dict(job_detail_context.reconciliation or {})
    execute_context.workflow = dict(job_detail_context.workflow or {})
    execute_context.pod_cod = dict(job_detail_context.pod_cod or {})
    execute_context.round_trip = dict(job_detail_context.round_trip or {})
    execute_context.timeline = dict(job_detail_context.timeline or {})
    execute_context.alerts = dict(job_detail_context.alerts or {})
    execute_context.sync_metadata = dict(job_detail_context.sync_metadata or {})
    execute_context.latest_action_log_id = (
        getattr(job_detail_context, 'latest_action_log_id', '') or ''
    )
    execute_context.content_hash = getattr(job_detail_context, 'content_hash', '') or ''
