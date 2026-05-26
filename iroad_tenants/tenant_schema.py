"""
Tenant portal DB schema helpers (django-tenants).

``TenantPortalSchemaMiddleware`` locks the subscriber schema for the full
``/tenant/`` request so template rendering and context processors do not reset
the connection to public while lazy querysets are still open.
"""
from __future__ import annotations

from django.db import connection


def is_portal_schema_locked(request) -> bool:
    return bool(getattr(request, '_tenant_portal_schema_locked', False))


def restore_public_schema(request=None) -> None:
    """Reset to public unless middleware owns the schema for this request."""
    if request is not None and is_portal_schema_locked(request):
        return
    connection.set_schema_to_public()


def lock_portal_tenant_schema(request, registry) -> None:
    request._tenant_portal_schema_locked = True
    request.tenant_workspace_registry = registry


def unlock_portal_tenant_schema(request) -> None:
    request._tenant_portal_schema_locked = False
    request.tenant_workspace_registry = None
    connection.set_schema_to_public()
