"""
Branded HTTP error pages (landing site design) and Django error handlers.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from iroad_frontend.exceptions import ServiceUnavailableError
from iroad_frontend.models import HomePageContent
from iroad_frontend.views import get_lang_context

logger = logging.getLogger(__name__)

ERROR_PAGES = {
    400: {
        'page_title': 'Bad request',
        'header_title': 'Bad request',
        'heading': 'Oops! invalid request',
        'message': (
            'The request could not be processed. '
            'Please check your input and try again.'
        ),
    },
    403: {
        'page_title': 'Access denied',
        'header_title': 'Access denied',
        'heading': 'Oops! access denied',
        'message': (
            'You do not have permission to view this page. '
            'Contact your administrator if you need access.'
        ),
    },
    404: {
        'page_title': 'Page not found',
        'header_title': 'Page not found',
        'heading': 'Oops! page not found',
        'message': 'The page you are looking for does not exist.',
    },
    500: {
        'page_title': 'Server error',
        'header_title': 'Server error',
        'heading': 'Oops! something went wrong',
        'message': (
            'We are having trouble completing your request right now. '
            'Please try again in a few minutes.'
        ),
    },
    503: {
        'page_title': 'Service unavailable',
        'header_title': 'Service unavailable',
        'heading': 'Oops! service temporarily unavailable',
        'message': (
            'A required background service is offline right now. '
            'Please try again shortly or contact support.'
        ),
    },
}

PORTAL_ERROR_PREFIXES = (
    '/tenant/',
    '/dashboard/',
    '/crm/',
    '/roles/',
    '/admin-users/',
    '/security/',
    '/master-data/',
    '/system-config/',
    '/subscription/',
    '/payment/',
    '/comm/',
    '/support/',
    '/cms/',
    '/login/',
    '/otp-verify/',
)


def _uses_portal_error_shell(request) -> bool:
    path = request.path or ''
    return any(path.startswith(prefix) for prefix in PORTAL_ERROR_PREFIXES)


def _wants_json_response(request) -> bool:
    path = (request.path or '').lower()
    if path.startswith('/api/'):
        return True
    accept = (request.META.get('HTTP_ACCEPT') or '').lower()
    if 'application/json' in accept and 'text/html' not in accept:
        return True
    requested_with = (request.META.get('HTTP_X_REQUESTED_WITH') or '').lower()
    return requested_with == 'xmlhttprequest'


def _json_error_payload(status_code: int, detail: str | None = None) -> dict:
    page = ERROR_PAGES.get(status_code, ERROR_PAGES[500])
    return {
        'error': page['page_title'],
        'detail': detail or page['message'],
        'status': status_code,
    }


def _resolve_home_navigation(request) -> dict:
    path = request.path or ''
    if path.startswith('/tenant/'):
        try:
            return {
                'home_url': reverse('iroad_tenants:tenant_dashboard'),
                'home_label': 'Back to Dashboard',
            }
        except NoReverseMatch:
            pass

    admin_prefixes = (
        '/dashboard/',
        '/crm/',
        '/roles/',
        '/admin-users/',
        '/security/',
        '/master-data/',
        '/system-config/',
        '/subscription/',
        '/payment/',
        '/comm/',
        '/support/',
        '/cms/',
        '/login/',
        '/otp-verify/',
    )
    if any(path.startswith(prefix) for prefix in admin_prefixes):
        if getattr(request, 'user', None) and request.user.is_authenticated:
            try:
                return {
                    'home_url': reverse('dashboard'),
                    'home_label': 'Back to Dashboard',
                }
            except NoReverseMatch:
                pass
        try:
            return {
                'home_url': reverse('login'),
                'home_label': 'Back to Sign In',
            }
        except NoReverseMatch:
            pass

    try:
        return {
            'home_url': reverse('iroad_frontend:home'),
            'home_label': 'Back To Home',
        }
    except NoReverseMatch:
        return {'home_url': '/', 'home_label': 'Back To Home'}


def build_error_context(request, status_code: int, *, detail: str | None = None) -> dict:
    page = ERROR_PAGES.get(status_code, ERROR_PAGES[500])
    ctx = {
        'error_code': status_code,
        'page_title': page['page_title'],
        'header_title': page['header_title'],
        'heading': page['heading'],
        'message': detail or page['message'],
    }
    if _uses_portal_error_shell(request):
        ctx.update({'lang': 'en', 'dir': 'ltr'})
    else:
        ctx['home'] = HomePageContent.get_singleton()
        ctx.update(get_lang_context(request))
    ctx.update(_resolve_home_navigation(request))
    return ctx


def _resolve_error_template(request, status_code: int) -> str:
    if _uses_portal_error_shell(request):
        return 'errors/standalone.html'
    return f'iroad_frontend/errors/{status_code}.html'


def render_error_page(request, status_code: int, *, detail: str | None = None):
    if _wants_json_response(request):
        return JsonResponse(
            _json_error_payload(status_code, detail=detail),
            status=status_code,
        )
    template_name = _resolve_error_template(request, status_code)
    return render(
        request,
        template_name,
        build_error_context(request, status_code, detail=detail),
        status=status_code,
    )


def page_not_found(request, exception=None):
    return render_error_page(request, 404)


def permission_denied(request, exception=None):
    detail = str(exception) if exception else None
    return render_error_page(request, 403, detail=detail)


def bad_request(request, exception=None):
    detail = str(exception) if exception else None
    return render_error_page(request, 400, detail=detail)


def server_error(request):
    return render_error_page(request, 500)


def service_unavailable(request, exception=None):
    detail = str(exception) if exception else None
    return render_error_page(request, 503, detail=detail)


def error_preview(request, code: int):
    """Preview branded error pages while DEBUG=True."""
    if not settings.DEBUG:
        raise Http404
    code = int(code)
    if code not in ERROR_PAGES:
        raise Http404
    # Force portal shell when previewing under /tenant/.
    return render_error_page(request, code)


def handle_exception_for_custom_page(request, exception):
    """
    Map raised exceptions to branded pages when USE_CUSTOM_ERROR_PAGES is enabled.
    Returns an HttpResponse/JsonResponse or None to fall through.
    """
    if isinstance(exception, Http404):
        return page_not_found(request, exception)
    if isinstance(exception, PermissionDenied):
        return permission_denied(request, exception)
    if isinstance(exception, SuspiciousOperation):
        return bad_request(request, exception)
    if isinstance(exception, ServiceUnavailableError):
        return service_unavailable(request, exception)

    if getattr(settings, 'USE_CUSTOM_ERROR_PAGES', False):
        logger.exception('Unhandled exception for request %s', request.path)
        return server_error(request)
    return None
