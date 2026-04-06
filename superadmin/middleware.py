from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.db import connection
from django.shortcuts import redirect


class TenantApiSchemaMiddleware:
    """
    For **tenant-originated** ``/api/v1/*`` bridge traffic: when ``X-Tenant-ID`` is
    present, switch to that subscriber's Postgres schema for tenant-local ORM.

    This header is **not** used for Superadmin browser auth (CP stays on public
    schema via hostname/session). It identifies **which subscriber** the bridge
    call is for, alongside the API key in ``api_auth.resolve_tenant_api_request``.
    """

    API_PREFIX = '/api/v1/'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(self.API_PREFIX):
            return self.get_response(request)

        tenant_id = (request.headers.get('X-Tenant-ID') or '').strip()
        if not tenant_id:
            return self.get_response(request)

        connection.set_schema_to_public()
        try:
            from iroad_tenants.models import TenantRegistry

            reg = (
                TenantRegistry.objects.filter(
                    tenant_profile_id=tenant_id,
                )
                .select_related('tenant_profile')
                .first()
            )
            if (
                reg
                and reg.tenant_profile.account_status == 'Active'
            ):
                request.tenant = reg
                connection.set_tenant(reg)
        except Exception:
            # Leave on public; view may still 401
            pass

        return self.get_response(request)


class SessionTimeoutMiddleware:
    EXEMPT_URLS = [
        "/login/",
        "/logout/",
        "/set-password/",
        "/reset-password/",
        "/new-password/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for non-authenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for exempt URLs
        if any(request.path.startswith(url) for url in self.EXEMPT_URLS):
            return self.get_response(request)

        # Skip static and media files
        if request.path.startswith("/static/") or request.path.startswith("/media/"):
            return self.get_response(request)

        try:
            from superadmin.auth_helpers import get_security_settings
            from superadmin.redis_helpers import refresh_admin_session

            settings_obj = get_security_settings()
            timeout_minutes = settings_obj.session_timeout_minutes

            jti = request.session.get("jti")

            if not jti:
                # No JTI in session — force logout
                auth_logout(request)
                messages.warning(
                    request,
                    "Your session has expired. Please login again.",
                )
                return redirect("/login/")

            # Check Redis and refresh TTL
            session_alive = refresh_admin_session(jti, timeout_minutes)

            if not session_alive:
                # Redis key gone — session expired
                auth_logout(request)
                messages.warning(
                    request,
                    "Your session has expired. Please login again.",
                )
                return redirect("/login/")

        except Exception:
            # If Redis is down — fail safe, allow request
            pass

        return self.get_response(request)

