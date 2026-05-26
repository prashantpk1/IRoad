"""
mobile_api/helpers/dashboard_security.py

Dashboard route security helpers (tenant hint resolution, API prefix).
"""
from __future__ import annotations

from mobile_api.helpers.mobile_tenant import resolve_active_tenant_registry

DASHBOARD_API_PREFIX = '/api/v1/mobile/driver/dashboard'


def resolve_tenant_schema_from_header(tenant_hint: str) -> str | None:
    """Map ``X-Tenant-ID`` to ``schema_name`` when hint is a registry identifier."""
    reg = resolve_active_tenant_registry(tenant_hint)
    if reg is None:
        return None
    return str(getattr(reg, 'schema_name', '') or '').strip() or None
