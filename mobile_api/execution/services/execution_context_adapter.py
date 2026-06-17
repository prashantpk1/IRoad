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


def pivot_execute_context_to_born_shipment(
    context: ExecuteActionContext,
) -> bool:
    """
    After booking-scoped execute links a new shipment (Auto Shipment at A4), switch
    post-execute read model to shipment scope so workflow shows A5+ instead of
    stale booking-only actions (e.g. A8).
    """
    if context.job_type != 'booking':
        return False

    action_log = context.action_log
    shipment_ref = ''
    if action_log is not None:
        shipment_ref = str(
            getattr(action_log, 'shipment_id', None)
            or getattr(getattr(action_log, 'shipment', None), 'pk', None)
            or ''
        ).strip()
    if not shipment_ref:
        return False

    shipment = context.shipment
    ship_pk = ''
    if shipment is not None:
        ship_pk = str(
            getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
        ).strip()
    if not ship_pk or ship_pk != shipment_ref:
        from mobile_api.job_detail.guards.entity_lookup import lookup_shipment_by_reference

        shipment = lookup_shipment_by_reference(shipment_ref)
    if shipment is None:
        return False

    ship_id = str(
        getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None) or ''
    ).strip()
    if not ship_id:
        return False

    context.job_type = 'shipment'
    context.job_id = ship_id
    context.shipment = shipment
    context.booking = getattr(shipment, 'booking', None) or context.booking

    cache = getattr(context, '_execution_projection_cache', None)
    if cache is not None and hasattr(cache, 'reset_job_detail_scope'):
        cache.reset_job_detail_scope()

    return True
