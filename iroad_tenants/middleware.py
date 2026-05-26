"""
Middleware for the tenant web portal (``/tenant/`` URLs).
"""
from __future__ import annotations

from iroad_tenants.tenant_schema import lock_portal_tenant_schema, unlock_portal_tenant_schema


class TenantPortalSchemaMiddleware:
    """
    Keep the tenant workspace Postgres schema active for the entire portal request.

    Without this, context processors and helpers call ``set_schema_to_public()``
    during template rendering while form dropdowns still hold lazy querysets,
    causing ``InvalidCursorName`` and missing ``tenant_*`` table errors.
    """

    PREFIX = '/tenant/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        locked = False
        if request.path.startswith(self.PREFIX):
            from iroad_tenants.views import _activate_tenant_workspace_schema

            registry = _activate_tenant_workspace_schema(
                request,
                _debug_label='[portal-mw]',
            )
            if registry is not None:
                lock_portal_tenant_schema(request, registry)
                locked = True
        try:
            return self.get_response(request)
        finally:
            if locked:
                unlock_portal_tenant_schema(request)
