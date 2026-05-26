"""
mobile_api/dashboard/services/dashboard_cache_service.py

Server-side cache for expensive dashboard projections (read-only).

Caches ONLY: booking/movement cards, workflow, POD/COD summary.
Does NOT cache: auth, permissions, ownership, timeline, alerts assembly.
"""
from __future__ import annotations

import logging
from typing import Any

from django.core.cache import cache

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)
from mobile_api.dashboard.polling_constants import (
    CACHE_KEY_PREFIX,
    DASHBOARD_CACHE_ENABLED,
    DASHBOARD_CACHE_TTL_SECONDS,
)
from mobile_api.dashboard.services.dashboard_etag_service import (
    build_etag_from_fingerprint,
    fingerprint_digest,
)

logger = logging.getLogger('mobile_api.dashboard')


def cache_key_for_invalidation(
    tenant_schema: str,
    driver_pk: Any,
    invalidation_digest: str,
) -> str:
    return f'{CACHE_KEY_PREFIX}:{tenant_schema}:{driver_pk}:{invalidation_digest}'


def get_cached_projections(
    tenant_schema: str,
    driver_pk: Any,
    invalidation_fingerprint: dict[str, Any],
) -> dict[str, Any] | None:
    """Return cached projection bundle or ``None``."""
    if not DASHBOARD_CACHE_ENABLED:
        return None
    digest = fingerprint_digest(invalidation_fingerprint)
    key = cache_key_for_invalidation(tenant_schema, driver_pk, digest)
    try:
        return cache.get(key)
    except Exception:
        logger.exception('dashboard cache get failed key=%s', key)
        return None


def set_cached_projections(
    tenant_schema: str,
    driver_pk: Any,
    invalidation_fingerprint: dict[str, Any],
    *,
    context: DriverDashboardContext,
    content_fingerprint: dict[str, Any],
) -> str:
    """
    Store projection slices; returns ETag for the cached payload.
    """
    etag = build_etag_from_fingerprint(content_fingerprint)
    if not DASHBOARD_CACHE_ENABLED:
        return etag

    digest = fingerprint_digest(invalidation_fingerprint)
    key = cache_key_for_invalidation(tenant_schema, driver_pk, digest)
    recon = context.reconciliation or {}
    payload = {
        'etag': etag,
        'invalidation_digest': digest,
        'reconciliation_version': recon.get('reconciliation_version', ''),
        'workflow_projection_version': recon.get('workflow_projection_version', ''),
        'compliance_projection_version': recon.get('compliance_projection_version', ''),
        'booking_projection': dict(context.booking_projection or {}),
        'movement_projection': dict(context.movement_projection or {}),
        'workflow_projection': dict(context.workflow_projection or {}),
        'pod_cod_projection': dict(context.pod_cod_projection or {}),
        'reconciliation': dict(recon),
    }
    try:
        cache.set(key, payload, timeout=DASHBOARD_CACHE_TTL_SECONDS)
    except Exception:
        logger.exception('dashboard cache set failed key=%s', key)
    return etag


def apply_cached_projections_to_context(
    context: DriverDashboardContext,
    cached: dict[str, Any],
) -> None:
    """Hydrate context from a cache hit (projections + reconciliation only)."""
    context.booking_projection = dict(cached.get('booking_projection') or {})
    context.movement_projection = dict(cached.get('movement_projection') or {})
    context.workflow_projection = dict(cached.get('workflow_projection') or {})
    context.pod_cod_projection = dict(cached.get('pod_cod_projection') or {})
    context.reconciliation = dict(cached.get('reconciliation') or {})


def cached_etag(cached: dict[str, Any]) -> str:
    return str(cached.get('etag') or '')
