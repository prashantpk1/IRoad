"""
mobile_api/helpers/dashboard_request_cache.py

Per-request memoization for dashboard builds (avoids duplicate public-schema lookups).
"""
from __future__ import annotations

from typing import Any

_CACHE_ATTR = '_mobile_dashboard_cache'


def get_request_cache(request) -> dict[str, Any]:
    if request is None:
        return {}
    cache = getattr(request, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(request, _CACHE_ATTR, cache)
    return cache


def cache_get(request, key: str, default=None):
    return get_request_cache(request).get(key, default)


def cache_set(request, key: str, value: Any) -> None:
    get_request_cache(request)[key] = value


def resolve_tenant_profile_id(
    tenant_schema: str,
    *,
    request=None,
    prefetched: str | None = None,
) -> str | None:
    """
    Resolve ``TenantProfile`` PK for public-schema push/FCM queries.

    Uses ``prefetched`` when provided (from welcome context), else one registry
    query per request (memoized on ``request``).
    """
    if prefetched:
        return str(prefetched)

    cache_key = f'tenant_profile_id:{tenant_schema}'
    if request is not None:
        cached = cache_get(request, cache_key)
        if cached is not None:
            return cached

    from iroad_tenants.models import TenantRegistry

    reg = (
        TenantRegistry.objects.filter(schema_name=tenant_schema)
        .values_list('tenant_profile_id', flat=True)
        .first()
    )
    profile_id = str(reg) if reg else None
    if request is not None:
        cache_set(request, cache_key, profile_id)
    return profile_id
