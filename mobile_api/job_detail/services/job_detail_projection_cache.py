"""
mobile_api/job_detail/services/job_detail_projection_cache.py

Per-request Action Log bundle for one explicit job (reconcile + workflow + timeline).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mobile_api.job_detail.constants import JOB_DETAIL_ACTION_LOG_SCAN_LIMIT
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.guards.ownership import driver_pk

from iroad_tenants.operation_runtime.latest_action_aggregator import (
    scoped_movement_action_logs,
    scoped_shipment_action_logs,
)


@dataclass
class JobDetailProjectionCache:
    """In-memory per request — not shared across workers."""

    shipment_logs: list[Any] = field(default_factory=list)
    movement_logs: list[Any] = field(default_factory=list)
    latest_action_log_id: str = ''
    log_scan_limit: int = JOB_DETAIL_ACTION_LOG_SCAN_LIMIT
    queries_executed: int = 0

    def primary_logs(self) -> list[Any]:
        if self.shipment_logs:
            return self.shipment_logs
        return self.movement_logs


def load_projection_cache(context: JobDetailContext) -> JobDetailProjectionCache:
    """
    Bounded Action Log scan for the resolved explicit job.

    Attaches ``context.projection_cache`` and ``context.latest_action_log_id``.
    """
    existing = getattr(context, 'projection_cache', None)
    if isinstance(existing, JobDetailProjectionCache):
        return existing

    cache = JobDetailProjectionCache()
    driver_id = driver_pk(context.driver)
    if driver_id is None:
        context.projection_cache = cache
        return cache

    limit = JOB_DETAIL_ACTION_LOG_SCAN_LIMIT

    if context.job_type == 'shipment' and context.shipment is not None:
        cache.shipment_logs = list(
            scoped_shipment_action_logs(
                context.shipment,
                movement=None,
                driver_id=driver_id,
                scan_limit=limit,
            )
        )
        cache.queries_executed += 1
    elif context.job_type == 'movement' and context.movement is not None:
        cache.movement_logs = list(
            scoped_movement_action_logs(
                context.movement,
                driver_id=driver_id,
                scan_limit=limit,
            )
        )
        cache.queries_executed += 1

    logs = cache.primary_logs()
    if logs:
        head = logs[0]
        cache.latest_action_log_id = str(
            getattr(head, 'log_id', None) or getattr(head, 'pk', '') or ''
        )

    context.projection_cache = cache
    context.latest_action_log_id = cache.latest_action_log_id
    return cache


def get_projection_cache(context: JobDetailContext) -> JobDetailProjectionCache | None:
    cache = getattr(context, 'projection_cache', None)
    return cache if isinstance(cache, JobDetailProjectionCache) else None
