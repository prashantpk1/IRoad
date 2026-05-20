"""
mobile_api/helpers/dashboard_cache.py

Redis-backed slice caching for dashboard endpoints (fail-open if cache unavailable).
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger('mobile_api')

CACHE_VERSION = 'v2'


def _ttl(slice_name: str) -> int:
    overrides = {
        'full': 'MOBILE_API_DASHBOARD_CACHE_TTL_SECONDS',
        'summary': 'MOBILE_API_DASHBOARD_CACHE_TTL_SECONDS',
    }
    key = overrides.get(slice_name, 'MOBILE_API_DASHBOARD_SLICE_CACHE_TTL_SECONDS')
    default = 20 if slice_name in ('full', 'summary') else 20
    return max(0, int(getattr(settings, key, default) or default))


def cache_key(
    *,
    tenant_schema: str,
    driver_id: str,
    slice_name: str,
    extra: str = '',
) -> str:
    suffix = f':{extra}' if extra else ''
    return (
        f'mobile:dashboard:{CACHE_VERSION}:{tenant_schema}:'
        f'{driver_id}:{slice_name}{suffix}'
    )


def cache_get(*, tenant_schema: str, driver_id: str, slice_name: str, extra: str = ''):
    ttl = _ttl(slice_name)
    if ttl <= 0:
        return None
    try:
        from django.core.cache import cache

        value = cache.get(
            cache_key(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                slice_name=slice_name,
                extra=extra,
            )
        )
        if value is not None:
            logger.debug(
                'dashboard.cache hit slice=%s schema=%s driver=%s',
                slice_name,
                tenant_schema,
                driver_id,
            )
        return value
    except Exception as exc:
        logger.warning('dashboard.cache get failed: %s', exc)
        return None


def cache_set(
    *,
    tenant_schema: str,
    driver_id: str,
    slice_name: str,
    data: Any,
    extra: str = '',
) -> None:
    ttl = _ttl(slice_name)
    if ttl <= 0:
        return
    try:
        from django.core.cache import cache

        cache.set(
            cache_key(
                tenant_schema=tenant_schema,
                driver_id=driver_id,
                slice_name=slice_name,
                extra=extra,
            ),
            data,
            timeout=ttl,
        )
    except Exception as exc:
        logger.warning('dashboard.cache set failed: %s', exc)


def invalidate_driver_dashboard_cache(
    *,
    tenant_schema: str,
    driver_id: str,
) -> None:
    """Best-effort invalidation when driver operational data changes."""
    try:
        from django.core.cache import cache

        for slice_name in (
            'full',
            'summary',
            'current_job',
            'quick_actions',
            'counters',
            'notifications',
        ):
            cache.delete(
                cache_key(
                    tenant_schema=tenant_schema,
                    driver_id=driver_id,
                    slice_name=slice_name,
                )
            )
    except Exception as exc:
        logger.debug('dashboard.cache invalidate failed: %s', exc)
