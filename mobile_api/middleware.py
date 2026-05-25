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

Dashboard routes additionally use ``MobileDashboardSecurityMiddleware`` (tenant
hint vs JWT, read-only verbs) and DRF ``HasDriverDashboardAccess``.
"""
from __future__ import annotations

import logging
import time

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


class MobileJobListSecurityMiddleware:
    """
    Defense-in-depth for ``/api/v1/mobile/driver/jobs/*``.

    - **Read** routes: GET/HEAD/OPTIONS only + tenant hint vs JWT check.
    - **Execution** routes (execute / upload-pod / collect-cod): allow POST with
      the same tenant hint binding (RBAC + view guards enforce authorization).
    """

    SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})
    EXECUTION_METHODS = frozenset({'POST'})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from mobile_api.helpers.job_list_security import JOBS_API_PREFIX
        from mobile_api.helpers.job_execution_security import (
            is_jobs_execution_post_path,
        )
        from mobile_api.helpers.dashboard_security import resolve_tenant_schema_from_header
        from mobile_api.helpers.middleware_request_sim import (
            ensure_request_observability_attrs,
        )

        request = ensure_request_observability_attrs(request)
        path = request.path
        if not path.startswith(JOBS_API_PREFIX):
            return self.get_response(request)

        request.mobile_job_list_route = True
        import time

        from mobile_api.helpers.job_list_observability import SLOW_MS

        started = time.perf_counter()
        method = request.method

        is_execution_post = (
            method in self.EXECUTION_METHODS
            and is_jobs_execution_post_path(path)
        )
        if is_execution_post:
            request.mobile_job_execution_route = True
        elif method not in self.SAFE_METHODS:
            return JsonResponse(
                {
                    'status': 0,
                    'message': str(_('mobile.auth.jobs_method_not_allowed')),
                    'data': {'error_code': 'jobs_method_not_allowed'},
                },
                status=405,
            )

        try:
            from django.conf import settings

            if not getattr(
                settings,
                'MOBILE_API_JOBS_MIDDLEWARE_ENFORCE_TENANT',
                True,
            ):
                return _jobs_finish_request(self, request, started)
        except Exception:
            return _jobs_finish_request(self, request, started)

        tenant_hint = (request.headers.get('X-Tenant-ID') or '').strip()
        if not tenant_hint:
            return _jobs_finish_request(self, request, started)

        from mobile_api.helpers.auth import (
            TOKEN_TYPE_ACCESS,
            get_token_from_request,
            verify_token,
        )

        token = get_token_from_request(request)
        if not token:
            return _jobs_finish_request(self, request, started)

        try:
            payload = verify_token(token, expected_type=TOKEN_TYPE_ACCESS)
        except Exception:
            return _jobs_finish_request(self, request, started)

        if not payload:
            return _jobs_finish_request(self, request, started)

        token_schema = str(payload.get('tenant_schema') or '').strip()
        hint_schema = resolve_tenant_schema_from_header(tenant_hint)
        if hint_schema and token_schema and hint_schema != token_schema:
            try:
                from mobile_api.helpers.security_audit import (
                    client_ip_from_request as _sec_ip,
                    log_mobile_security_event,
                )

                log_mobile_security_event(
                    'jobs_middleware_tenant_mismatch',
                    schema=token_schema,
                    ip=_sec_ip(request),
                    reason=f'hint={hint_schema[:64]}',
                )
            except Exception:
                pass
            logger.warning(
                'jobs.middleware tenant_mismatch token=%s hint=%s path=%s',
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

        return _jobs_finish_request(self, request, started)


def _jobs_finish_request(middleware, request, started: float):
    """Return response and log end-to-end slow job-list / job-detail requests."""
    from mobile_api.helpers.job_detail_observability import (
        SLOW_MS as DETAIL_SLOW_MS,
        classify_job_detail_operation,
        record_middleware_timing,
    )
    from mobile_api.helpers.job_list_observability import SLOW_MS
    from mobile_api.helpers.middleware_request_sim import ensure_request_observability_attrs

    request = ensure_request_observability_attrs(request)
    path = request.path
    method = request.method

    try:
        response = middleware.get_response(request)
    except Exception:
        logger.exception(
            'jobs.middleware handler_error path=%s method=%s',
            path[:120],
            method,
        )
        raise

    try:
        elapsed_ms = (time.perf_counter() - started) * 1000
        slow_threshold = DETAIL_SLOW_MS if '/jobs/' in path else SLOW_MS
        op = classify_job_detail_operation(path, method)
        record_middleware_timing(
            operation=op,
            elapsed_ms=elapsed_ms,
            path=path,
            slow_threshold_ms=slow_threshold,
        )
    except Exception:
        logger.exception(
            'jobs.middleware metrics_error path=%s method=%s',
            path[:120],
            method,
        )
    return response
