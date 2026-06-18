from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse


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

        tenant_identifier = (request.headers.get('X-Tenant-ID') or '').strip()
        if not tenant_identifier:
            return self.get_response(request)

        connection.set_schema_to_public()
        try:
            from iroad_tenants.models import TenantRegistry

            # Accept either tenant UUID (tenant_profile_id) or schema_name.
            # Mobile clients may send one or the other while migrating.
            reg = (
                TenantRegistry.objects.filter(
                    Q(tenant_profile_id=tenant_identifier)
                    | Q(schema_name=tenant_identifier)
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
    EXEMPT_ROUTE_NAMES = (
        "login",
        "logout",
        "set_password",
        "reset_password",
        "new_password",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def _resolved_exempt_paths(self):
        paths = []
        for route_name in self.EXEMPT_ROUTE_NAMES:
            try:
                paths.append(reverse(route_name))
            except NoReverseMatch:
                continue
        return tuple(paths)

    def _login_url(self):
        configured = (getattr(settings, "LOGIN_URL", "") or "").strip()
        if configured:
            return configured
        try:
            return reverse("login")
        except NoReverseMatch:
            return "/login/"

    def __call__(self, request):
        # Skip for non-authenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for exempt URLs
        exempt_paths = self._resolved_exempt_paths()
        if exempt_paths and request.path.startswith(exempt_paths):
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
                return redirect(self._login_url())

            # Check Redis and refresh TTL
            session_alive = refresh_admin_session(jti, timeout_minutes)

            # Redis down — allow request (degraded mode, same as previous fail-safe).
            if session_alive is None:
                return self.get_response(request)

            if not session_alive:
                # Redis key gone — session expired
                auth_logout(request)
                messages.warning(
                    request,
                    "Your session has expired. Please login again.",
                )
                return redirect(self._login_url())

        except Exception:
            # If Redis is down — fail safe, allow request
            pass

        return self.get_response(request)

