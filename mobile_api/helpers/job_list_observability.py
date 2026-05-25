"""
mobile_api/helpers/job_list_observability.py

Structured timing, slow-request detection, and operational metrics for job list APIs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from django.conf import settings

logger = logging.getLogger('mobile_api.jobs')

SLOW_MS = int(getattr(settings, 'MOBILE_API_JOBS_SLOW_REQUEST_MS', 1200) or 1200)


def _metric_enabled() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_METRICS_ENABLED', True))


@contextmanager
def job_list_timer(
    *,
    operation: str,
    tenant_schema: str = '',
    driver_id: str = '',
    entity_type: str = '',
    extra: str | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Time an operation; log warning when slower than ``MOBILE_API_JOBS_SLOW_REQUEST_MS``.

    Yields a mutable metrics dict for callers to populate (query_ms, item_count, etc.).
    """
    metrics: dict[str, Any] = {
        'operation': operation,
        'entity_type': entity_type,
    }
    start = time.perf_counter()
    try:
        yield metrics
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        metrics['elapsed_ms'] = round(elapsed_ms, 2)
        msg = (
            f'jobs.{operation} schema={tenant_schema} driver={driver_id} '
            f'ms={elapsed_ms:.1f}'
        )
        if entity_type:
            msg = f'{msg} entity={entity_type}'
        if extra:
            msg = f'{msg} {extra}'
        for key in (
            'item_count',
            'page',
            'page_size',
            'cache_hit',
            'include_total',
            'pagination_mode',
            'search_term',
            'payload_bytes',
            'payload_truncated',
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
    if not _metric_enabled():
        return
    try:
        from mobile_api.helpers.security_audit import log_mobile_security_event

        log_mobile_security_event(
            'job_list_slow_request',
            schema=tenant_schema[:64],
            ip='',
            reason=(
                f'op={operation[:32]} driver={driver_id[:36]} '
                f'ms={elapsed_ms:.0f} items={metrics.get("item_count", "")}'
            )[:200],
        )
    except Exception:
        pass


def estimate_payload_bytes(items: list) -> int:
    """Rough JSON byte size for response payload protection."""
    if not items:
        return 2
    try:
        return len(json.dumps(items, default=str).encode('utf-8'))
    except Exception:
        return 0


def build_count_fingerprint(
    *,
    entity_type: str,
    filters,
    sort: str,
    include_actions: bool,
) -> str:
    """Cache key for optional COUNT — excludes page/cursor."""
    return filters_fingerprint(
        entity_type=entity_type,
        tab=filters.tab,
        queue=filters.queue,
        search=filters.search,
        sort=sort,
        date_from=filters.date_from or '',
        date_to=filters.date_to or '',
        date_field=filters.date_field,
        page=0,
        page_size=0,
        include_actions=include_actions,
        include_total=True,
    )


def log_payload_size(
    *,
    operation: str,
    items: list,
    tenant_schema: str = '',
    driver_id: str = '',
) -> int:
    """Log when list payload exceeds ``MOBILE_API_JOBS_MAX_RESPONSE_BYTES``."""
    size = estimate_payload_bytes(items)
    cap = int(getattr(settings, 'MOBILE_API_JOBS_MAX_RESPONSE_BYTES', 524288) or 524288)
    if size > cap:
        logger.warning(
            'jobs.payload_oversize op=%s schema=%s driver=%s bytes=%s cap=%s items=%s',
            operation,
            tenant_schema,
            driver_id,
            size,
            cap,
            len(items),
        )
    return size


def filters_fingerprint(
    *,
    entity_type: str,
    tab: str,
    queue: str,
    search: str,
    sort: str,
    date_from: str,
    date_to: str,
    date_field: str,
    page: int,
    page_size: int,
    include_actions: bool,
    include_total: bool,
) -> str:
    """Stable cache key suffix for list requests."""
    raw = '|'.join(
        [
            entity_type,
            tab,
            queue,
            search[:64],
            sort,
            date_from or '',
            date_to or '',
            date_field,
            str(page),
            str(page_size),
            '1' if include_actions else '0',
            '1' if include_total else '0',
        ]
    )
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]
