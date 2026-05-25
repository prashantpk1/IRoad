"""
Threading helpers for Job Detail PostgreSQL concurrency E2E tests.

Each worker closes Django DB connections before/after work and runs inside
``schema_context`` so tenant ORM paths match production.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from django.db import connection, connections

T = TypeVar('T')


def close_all_db_connections() -> None:
    connections.close_all()


def run_in_tenant_schema(tenant_schema: str, fn: Callable[[], T]) -> T:
    """
    Run ``fn`` on this thread's DB connection inside ``schema_context``.

    Matches ``test_job_detail_db_execution`` threading pattern: close stale
    connection, then enter tenant schema (thread-local connections).
    """
    from django_tenants.utils import schema_context

    connections['default'].close()
    with schema_context(tenant_schema):
        return fn()


def run_parallel(
    workers: list[Callable[[], Any]],
    *,
    timeout: float = 90.0,
    start_barrier: bool = False,
) -> tuple[list[Any], list[BaseException]]:
    """
    Run callables on separate threads.

    When ``start_barrier`` is True, all workers block on a ``Barrier`` so they
    start together (simultaneous execute / race tests).
    """
    n = len(workers)
    if n == 0:
        return [], []

    results: list[Any] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n) if start_barrier and n > 1 else None

    def _worker(fn: Callable[[], Any]) -> None:
        try:
            if barrier is not None:
                barrier.wait(timeout=min(timeout, 30.0))
            out = fn()
            with lock:
                results.append(out)
        except BaseException as exc:
            with lock:
                errors.append(exc)
        finally:
            connections['default'].close()

    threads = [threading.Thread(target=_worker, args=(w,)) for w in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    alive = [t for t in threads if t.is_alive()]
    if alive:
        raise TimeoutError(
            f'{len(alive)} worker thread(s) did not finish within {timeout}s',
        )
    return results, errors


def execution_request_for_body(validated_body: dict):
    """
    Minimal request stand-in for ``validate_mobile_execution_payload`` (no DRF parser).
    """

    class _DataMapping(dict):
        def getlist(self, key, default=None):
            value = self.get(key, default)
            if value is None:
                return []
            if isinstance(value, list):
                return value
            return [value]

    class _PayloadRequest:
        def __init__(self, data: dict):
            self.data = _DataMapping({k: v for k, v in data.items()})
            self.FILES = _DataMapping()
            self.headers = {}
            self.META = {}

    return _PayloadRequest(validated_body)


def enrich_execute_body(body: dict) -> dict:
    """Defaults so Action Master GPS/note metadata is satisfied in service tests."""
    out = dict(body)
    out.setdefault('latitude', '24.713600')
    out.setdefault('longitude', '46.675300')
    if not (out.get('notes') or '').strip():
        out['notes'] = 'job-detail-concurrency-e2e'
    return out


def count_logs_with_idempotency_key(
    *,
    idempotency_key: str,
    shipment_pk=None,
    movement_pk=None,
) -> int:
    from tenant_workspace.models import TenantOperationActionLog

    qs = TenantOperationActionLog.objects.filter(
        idempotency_key=idempotency_key,
    )
    if shipment_pk is not None:
        qs = qs.filter(shipment_id=shipment_pk)
    if movement_pk is not None:
        qs = qs.filter(truck_movement_id=movement_pk)
    return qs.count()
