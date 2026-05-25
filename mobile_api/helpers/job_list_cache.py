"""
mobile_api/helpers/job_list_cache.py

Redis-backed caching for job list summary (fail-open).

List pages are not cached by default (high churn + filter permutations); use short
TTL only when ``MOBILE_API_JOBS_LIST_CACHE_TTL_SECONDS`` > 0 for locked-tab polls.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from mobile_api.helpers.job_list_observability import filters_fingerprint

logger = logging.getLogger('mobile_api.jobs')

CACHE_VERSION = 'v1'


def _summary_ttl() -> int:
    return max(0, int(getattr(settings, 'MOBILE_API_JOBS_SUMMARY_CACHE_TTL_SECONDS', 30) or 30))


def _list_ttl() -> int:
    return max(0, int(getattr(settings, 'MOBILE_API_JOBS_LIST_CACHE_TTL_SECONDS', 0) or 0))


def summary_cache_key(*, tenant_schema: str, driver_id: str) -> str:
    return f'mobile:jobs:{CACHE_VERSION}:summary:{tenant_schema}:{driver_id}'


def list_cache_key(
    *,
    tenant_schema: str,
    driver_id: str,
    fingerprint: str,
) -> str:
    return f'mobile:jobs:{CACHE_VERSION}:list:{tenant_schema}:{driver_id}:{fingerprint}'


def cache_get(key: str) -> Any:
    try:
        from django.core.cache import cache

        return cache.get(key)
    except Exception as exc:
        logger.warning('jobs.cache get failed: %s', exc)
        return None


def cache_set(*, key: str, data: Any, ttl: int) -> None:
    if ttl <= 0:
        return
    try:
        from django.core.cache import cache

        cache.set(key, data, timeout=ttl)
    except Exception as exc:
        logger.warning('jobs.cache set failed: %s', exc)


def get_cached_job_summary(*, tenant_schema: str, driver_id: str) -> dict[str, Any] | None:
    ttl = _summary_ttl()
    if ttl <= 0:
        return None
    key = summary_cache_key(tenant_schema=tenant_schema, driver_id=driver_id)
    hit = cache_get(key)
    if hit is not None:
        logger.debug('jobs.cache hit summary schema=%s driver=%s', tenant_schema, driver_id)
    return hit


def set_cached_job_summary(
    *,
    tenant_schema: str,
    driver_id: str,
    payload: dict[str, Any],
) -> None:
    cache_set(
        key=summary_cache_key(tenant_schema=tenant_schema, driver_id=driver_id),
        data=payload,
        ttl=_summary_ttl(),
    )


def get_cached_list_page(
    *,
    tenant_schema: str,
    driver_id: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    ttl = _list_ttl()
    if ttl <= 0:
        return None
    return cache_get(
        list_cache_key(
            tenant_schema=tenant_schema,
            driver_id=driver_id,
            fingerprint=fingerprint,
        )
    )


def set_cached_list_page(
    *,
    tenant_schema: str,
    driver_id: str,
    fingerprint: str,
    payload: dict[str, Any],
) -> None:
    cache_set(
        key=list_cache_key(
            tenant_schema=tenant_schema,
            driver_id=driver_id,
            fingerprint=fingerprint,
        ),
        data=payload,
        ttl=_list_ttl(),
    )


def build_list_fingerprint(
    *,
    entity_type: str,
    filters,
    sort: str,
    page: int,
    page_size: int,
    include_actions: bool,
    include_total: bool,
) -> str:
    return filters_fingerprint(
        entity_type=entity_type,
        tab=filters.tab,
        queue=filters.queue,
        search=filters.search,
        sort=sort,
        date_from=filters.date_from or '',
        date_to=filters.date_to or '',
        date_field=filters.date_field,
        page=page,
        page_size=page_size,
        include_actions=include_actions,
        include_total=include_total,
    )


def count_cache_key(*, tenant_schema: str, driver_id: str, fingerprint: str) -> str:
    return f'mobile:jobs:{CACHE_VERSION}:count:{tenant_schema}:{driver_id}:{fingerprint}'


def get_cached_list_total(
    *,
    tenant_schema: str,
    driver_id: str,
    fingerprint: str,
) -> int | None:
    ttl = max(0, int(getattr(settings, 'MOBILE_API_JOBS_COUNT_CACHE_TTL_SECONDS', 60) or 60))
    if ttl <= 0:
        return None
    hit = cache_get(count_cache_key(
        tenant_schema=tenant_schema,
        driver_id=driver_id,
        fingerprint=fingerprint,
    ))
    if hit is not None:
        try:
            return int(hit)
        except (TypeError, ValueError):
            return None
    return None


def set_cached_list_total(
    *,
    tenant_schema: str,
    driver_id: str,
    fingerprint: str,
    total: int,
) -> None:
    ttl = max(0, int(getattr(settings, 'MOBILE_API_JOBS_COUNT_CACHE_TTL_SECONDS', 60) or 60))
    cache_set(
        key=count_cache_key(
            tenant_schema=tenant_schema,
            driver_id=driver_id,
            fingerprint=fingerprint,
        ),
        data=int(total),
        ttl=ttl,
    )


def invalidate_driver_job_list_cache(
    *,
    tenant_schema: str,
    driver_id: str,
) -> None:
    """Best-effort summary invalidation after operational writes."""
    try:
        from django.core.cache import cache

        cache.delete(summary_cache_key(tenant_schema=tenant_schema, driver_id=driver_id))
    except Exception as exc:
        logger.warning('jobs.cache invalidate failed: %s', exc)
