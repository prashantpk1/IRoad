"""
mobile_api/middleware.py

Mobile API request hooks.

``MobileApiSecurityHeadersMiddleware`` adds cache and browser-oriented security
headers for JSON under ``/api/v1/mobile/``.

**RBAC** (roles and capabilities) is enforced by DRF ``permission_classes`` and
``mobile_api.rbac``, not by HTTP middleware, so anonymous routes stay fast and
rules stay co-located with each view.

Driver **session** checks (active user + active driver + tenant consistency) run
in ``MobileJWTAuthentication`` / ``resolve_mobile_driver_session``.
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

        # Avoid caching authenticated JSON (tokens, PII in error bodies).
        response.setdefault('Cache-Control', 'no-store, private')
        response.setdefault('Pragma', 'no-cache')
        # Explicit nosniff (SecurityMiddleware also sets when SECURE_CONTENT_TYPE_NOSNIFF).
        response.setdefault('X-Content-Type-Options', 'nosniff')
        # Referrer leakage from deep links / WebViews
        policy = getattr(
            settings,
            'MOBILE_API_REFERRER_POLICY',
            'strict-origin-when-cross-origin',
        )
        if policy:
            response.setdefault('Referrer-Policy', str(policy))
        # Narrow feature surface for any in-app browser contexts
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
