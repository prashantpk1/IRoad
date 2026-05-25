"""
Tenant-scoped cache for the ACTIVE Action Config catalog.

Avoids repeated full-table scans of ``tenant_operation_actions`` within a short
TTL window. Invalidates automatically when any action row's ``updated_at`` changes.
"""

from __future__ import annotations

from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Max

from tenant_workspace.models import TenantOperationAction

_CACHE_PREFIX = 'iroad:active_op_action_ids'
_DEFAULT_TTL = 120


def _tenant_schema_name() -> str:
    return getattr(connection, 'schema_name', None) or 'public'


def _catalog_cache_key() -> str | None:
    agg = TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).aggregate(
        version=Max('updated_at'),
        total=Count('pk'),
    )
    version = agg.get('version')
    if version is None:
        return None
    return '|'.join(
        [
            _CACHE_PREFIX,
            _tenant_schema_name(),
            str(agg.get('total') or 0),
            version.isoformat() if hasattr(version, 'isoformat') else str(version),
        ]
    )


def get_cached_active_action_ids(*, ttl: int | None = None) -> list | None:
    """
    Return cached ACTIVE action PKs for the current tenant schema, or None on miss.
    """
    key = _catalog_cache_key()
    if key is None:
        return []
    hit = cache.get(key)
    if hit is not None:
        return list(hit)
    ids = list(
        TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        )
        .order_by('sequence_number', 'action_code')
        .values_list('pk', flat=True)
    )
    cache.set(key, ids, timeout=ttl if ttl is not None else _DEFAULT_TTL)
    return ids


def invalidate_active_action_catalog_cache() -> None:
    """Best-effort bust after Action Master writes (admin / imports)."""
    key = _catalog_cache_key()
    if key:
        cache.delete(key)


def active_operation_actions_queryset(*, use_catalog_cache: bool = True):
    """
    ACTIVE actions for policy evaluation, optionally seeded from catalog cache.
    """
    if use_catalog_cache:
        cached_ids = get_cached_active_action_ids()
        if cached_ids is not None:
            if not cached_ids:
                return TenantOperationAction.objects.none()
            return TenantOperationAction.objects.filter(
                action_id__in=cached_ids,
                status=TenantOperationAction.Status.ACTIVE,
            ).order_by('sequence_number', 'action_code')
    return TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).order_by('sequence_number', 'action_code')
