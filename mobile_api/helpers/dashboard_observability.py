"""
mobile_api/helpers/dashboard_observability.py

Structured timing logs for dashboard operations.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

from django.conf import settings

logger = logging.getLogger('mobile_api.dashboard')

SLOW_MS = int(getattr(settings, 'MOBILE_API_DASHBOARD_SLOW_REQUEST_MS', 800) or 800)


@contextmanager
def dashboard_timer(
    *,
    operation: str,
    tenant_schema: str = '',
    driver_id: str = '',
    extra: str | None = None,
) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        msg = (
            f'dashboard.{operation} schema={tenant_schema} driver={driver_id} '
            f'ms={elapsed_ms:.1f}'
        )
        if extra:
            msg = f'{msg} {extra}'
        if elapsed_ms >= SLOW_MS:
            logger.warning(msg)
        else:
            logger.info(msg)
