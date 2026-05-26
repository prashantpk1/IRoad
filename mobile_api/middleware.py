"""
mobile_api/middleware.py

Mobile API request hooks.

``MobileApiSecurityHeadersMiddleware`` adds cache and browser-oriented security
headers for JSON under ``/api/v1/mobile/``.

**RBAC** (roles and capabilities) is enforced by DRF ``permission_classes`` and
``mobile_api.rbac``, not by HTTP middleware.

Driver **session** checks (active user + active driver + tenant consistency) run
in ``MobileJWTAuthentication`` / ``resolve_mobile_driver_session``.

Dashboard routes additionally use ``MobileDashboardSecurityMiddleware`` (tenant
hint vs JWT, read-only verbs).
"""
from __future__ import annotations

import logging

from django.http import JsonResponse
from django.utils.translation import gettext as _

logger = logging.getLogger('mobile_api')

MOBILE_API_PREFIX = '/api/v1/mobile/'


class MobileApiSecurityHeadersMiddleware:
    """
    Add defense-in-depth HTTP headers for **mobile JSON API** responses.

    Native apps still pass through HTTP stacks (proxies, WebViews); ``no-store``
    reduces accidental caching of bearer responses. Toggled via
    ``MOBILE_API_SECURITY_HEADERS_ENABLED`` (default True).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            from django.conf import settings

            if not getattr(settings, 'MOBILE_API_SECURITY_HEADERS_ENABLED', True):
                return response
        except Exception:
            return response

        if not request.path.startswith(MOBILE_API_PREFIX):
            return response

        response.setdefault('Cache-Control', 'no-store, private')
        response.setdefault('Pragma', 'no-cache')
        response.setdefault('X-Content-Type-Options', 'nosniff')
        policy = getattr(
            settings,
            'MOBILE_API_REFERRER_POLICY',
            'strict-origin-when-cross-origin',
        )
        if policy:
            response.setdefault('Referrer-Policy', str(policy))
        perm = getattr(
            settings,
            'MOBILE_API_PERMISSIONS_POLICY',
            'camera=(), microphone=(), geolocation=()',
        )
        if perm:
            response.setdefault('Permissions-Policy', str(perm))
        return response


class MobileApiTenantGateMiddleware:
    """
    When ``X-Tenant-ID`` is sent on mobile API paths, require that it resolves to
    an **active** ``TenantRegistry`` row (UUID or ``schema_name``).

    Valid headers continue to ``TenantApiSchemaMiddleware`` / views unchanged.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(MOBILE_API_PREFIX):
            return self.get_response(request)

        tid = (request.headers.get('X-Tenant-ID') or '').strip()
        if not tid:
            return self.get_response(request)

        from mobile_api.helpers.mobile_tenant import resolve_active_tenant_registry

        if resolve_active_tenant_registry(tid) is None:
            try:
                from mobile_api.helpers.security_audit import (
                    client_ip_from_request as _sec_ip,
                    log_mobile_security_event,
                )

                log_mobile_security_event(
                    'mobile_invalid_x_tenant_id',
                    schema='',
                    ip=_sec_ip(request),
                    reason=request.path[:200],
                )
            except Exception:
                pass
            logger.info(
                'mobile.middleware invalid_x_tenant_id path=%s ip=%s',
                request.path,
                (request.META.get('REMOTE_ADDR') or '-')[:45],
            )
            return JsonResponse(
                {
                    'status': 0,
                    'message': str(_('mobile.auth.invalid_tenant')),
                    'data': {'error_code': 'invalid_tenant'},
                },
                status=400,
            )

        return self.get_response(request)


class MobileDashboardSecurityMiddleware:
    """
    Defense-in-depth for ``/api/v1/mobile/driver/dashboard/*``.

    - Allows only safe read verbs (GET/HEAD/OPTIONS).
    - When Bearer + ``X-Tenant-ID`` are both sent, JWT ``tenant_schema`` must match
      the resolved registry schema (blocks cross-tenant leakage).
    """

    SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from mobile_api.helpers.dashboard_security import (
            DASHBOARD_API_PREFIX,
            resolve_tenant_schema_from_header,
        )

        if not request.path.startswith(DASHBOARD_API_PREFIX):
            return self.get_response(request)

        request.mobile_dashboard_route = True

        if request.method not in self.SAFE_METHODS:
            logger.info(
                'dashboard.middleware method_blocked method=%s path=%s',
                request.method,
                request.path[:120],
            )
            return JsonResponse(
                {
                    'status': 0,
                    'message': str(_('mobile.auth.dashboard_method_not_allowed')),
                    'data': {'error_code': 'dashboard_method_not_allowed'},
                },
                status=405,
            )

        try:
            from django.conf import settings

            if not getattr(
                settings,
                'MOBILE_API_DASHBOARD_MIDDLEWARE_ENFORCE_TENANT',
                True,
            ):
                return self.get_response(request)
        except Exception:
            return self.get_response(request)

        tenant_hint = (request.headers.get('X-Tenant-ID') or '').strip()
        if not tenant_hint:
            return self.get_response(request)

        from mobile_api.helpers.auth import (
            TOKEN_TYPE_ACCESS,
            get_token_from_request,
            verify_token,
        )

        token = get_token_from_request(request)
        if not token:
            return self.get_response(request)

        try:
            payload = verify_token(token, expected_type=TOKEN_TYPE_ACCESS)
        except Exception:
            return self.get_response(request)

        if not payload:
            return self.get_response(request)

        token_schema = str(payload.get('tenant_schema') or '').strip()
        hint_schema = resolve_tenant_schema_from_header(tenant_hint)
        if hint_schema and token_schema and hint_schema != token_schema:
            try:
                from mobile_api.helpers.security_audit import (
                    client_ip_from_request as _sec_ip,
                    log_mobile_security_event,
                )

                log_mobile_security_event(
                    'dashboard_middleware_tenant_mismatch',
                    schema=token_schema,
                    ip=_sec_ip(request),
                    reason=f'hint={hint_schema[:64]}',
                )
            except Exception:
                pass
            logger.warning(
                'dashboard.middleware tenant_mismatch token=%s hint=%s path=%s',
                token_schema,
                hint_schema,
                request.path[:120],
            )
            return JsonResponse(
                {
                    'status': 0,
                    'message': str(_('mobile.auth.tenant_mismatch')),
                    'data': {'error_code': 'tenant_mismatch'},
                },
                status=403,
            )

        return self.get_response(request)
