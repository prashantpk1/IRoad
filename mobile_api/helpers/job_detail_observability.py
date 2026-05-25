"""
mobile_api/helpers/job_detail_observability.py

Timing, slow-request detection, and execution metrics for Job Detail APIs.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from django.conf import settings

logger = logging.getLogger('mobile_api.jobs.detail')

SLOW_MS = int(
    getattr(settings, 'MOBILE_API_JOBS_DETAIL_SLOW_REQUEST_MS', 1500) or 1500
)


def _metrics_enabled() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_DETAIL_METRICS_ENABLED', True))


def classify_job_detail_operation(path: str, method: str = 'GET') -> str:
    """Stable operation label from URL path."""
    p = (path or '').lower()
    m = (method or 'GET').upper()
    if '/actions/execute/' in p:
        return 'execute_action'
    if '/upload-pod/' in p:
        return 'upload_pod'
    if '/collect-cod/' in p:
        return 'collect_cod'
    if '/timeline/' in p:
        return 'timeline'
    if '/actions/' in p and m == 'GET':
        return 'allowed_actions'
    if '/shipments/' in p and m == 'GET':
        return 'job_detail_shipment'
    if '/movements/' in p and m == 'GET':
        return 'job_detail_movement'
    return 'job_detail_other'


@contextmanager
def job_detail_timer(
    *,
    operation: str,
    tenant_schema: str = '',
    driver_id: str = '',
    extra: str | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Time a job-detail operation; log warning when slower than
    ``MOBILE_API_JOBS_DETAIL_SLOW_REQUEST_MS``.
    """
    metrics: dict[str, Any] = {'operation': operation}
    start = time.perf_counter()
    try:
        yield metrics
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        metrics['elapsed_ms'] = round(elapsed_ms, 2)
        msg = (
            f'jobs.detail.{operation} schema={tenant_schema} driver={driver_id} '
            f'ms={elapsed_ms:.1f}'
        )
        if extra:
            msg = f'{msg} {extra}'
        for key in (
            'item_count',
            'log_scan_count',
            'media_batch_count',
            'page_size',
            'has_next',
            'payload_bytes',
            'query_count',
            'transaction_ms',
            'reused_existing',
        ):
            if key in metrics:
                msg = f'{msg} {key}={metrics[key]}'
        if elapsed_ms >= SLOW_MS:
            logger.warning(msg)
            _emit_slow_event(
                operation=operation,
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                elapsed_ms=elapsed_ms,
                metrics=metrics,
            )
        else:
            logger.info(msg)


def _emit_slow_event(
    *,
    operation: str,
    tenant_schema: str,
    driver_id: str,
    elapsed_ms: float,
    metrics: dict[str, Any],
) -> None:
    if not _metrics_enabled():
        return
    try:
        from mobile_api.helpers.security_audit import log_mobile_security_event

        log_mobile_security_event(
            'job_detail_slow_request',
            schema=tenant_schema[:64],
            ip='',
            reason=(
                f'op={operation[:32]} driver={driver_id[:36]} '
                f'ms={elapsed_ms:.0f} logs={metrics.get("log_scan_count", "")}'
            )[:200],
        )
    except Exception:
        pass


@contextmanager
def execution_transaction_timer(
    *,
    operation: str,
    tenant_schema: str = '',
    driver_id: str = '',
) -> Iterator[dict[str, Any]]:
    """Metrics wrapper for transactional execute / POD / COD."""
    metrics: dict[str, Any] = {'operation': operation}
    start = time.perf_counter()
    try:
        yield metrics
    finally:
        metrics['transaction_ms'] = round((time.perf_counter() - start) * 1000, 2)
        elapsed = metrics['transaction_ms']
        msg = (
            f'jobs.execution.{operation} schema={tenant_schema} driver={driver_id} '
            f'txn_ms={elapsed:.1f}'
        )
        if metrics.get('reused_existing') is not None:
            msg = f'{msg} reused={metrics["reused_existing"]}'
        if elapsed >= SLOW_MS:
            logger.warning(msg)
        else:
            logger.info(msg)


def record_middleware_timing(
    *,
    operation: str,
    elapsed_ms: float,
    path: str,
    slow_threshold_ms: float,
) -> None:
    """Log jobs middleware timing without breaking the response lifecycle."""
    if elapsed_ms >= slow_threshold_ms:
        logger.warning(
            'jobs.middleware slow_request op=%s path=%s ms=%.1f',
            operation,
            (path or '')[:120],
            elapsed_ms,
        )
    else:
        logger.debug(
            'jobs.middleware op=%s path=%s ms=%.1f',
            operation,
            (path or '')[:120],
            elapsed_ms,
        )


def record_execution_outcome(
    *,
    operation: str,
    tenant_schema: str = '',
    driver_id: str = '',
    reused_existing: bool | None = None,
    drift_detected: bool | None = None,
    txn_ms: float | None = None,
) -> None:
    """Structured execution outcome for ops dashboards."""
    if not _metrics_enabled():
        return
    parts = [
        f'jobs.execution.outcome op={operation}',
        f'schema={tenant_schema}',
        f'driver={driver_id}',
    ]
    if reused_existing is not None:
        parts.append(f'reused={reused_existing}')
    if drift_detected is not None:
        parts.append(f'drift={drift_detected}')
    if txn_ms is not None:
        parts.append(f'txn_ms={txn_ms:.1f}')
    logger.info(' '.join(parts))


def maybe_record_query_count(metrics: dict[str, Any]) -> None:
    """When ``DEBUG`` and query logging enabled, attach ORM query count."""
    try:
        from django.conf import settings as dj_settings

        if not dj_settings.DEBUG:
            return
        from django.db import connection

        metrics['query_count'] = len(connection.queries)
    except Exception:
        pass
