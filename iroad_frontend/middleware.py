"""
Middleware for branded error pages (works with DEBUG=True when enabled).
"""
from django.conf import settings

from iroad_frontend.error_views import handle_exception_for_custom_page, render_error_page

ERROR_PAGES_STATUS_CODES = frozenset({400, 403, 404, 500, 503})


class CustomErrorPageMiddleware:
    """
    When USE_CUSTOM_ERROR_PAGES is True, render designer error templates instead of
    Django debug pages — including while DEBUG=True.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Exception as exc:
            if getattr(settings, 'USE_CUSTOM_ERROR_PAGES', False):
                replacement = handle_exception_for_custom_page(request, exc)
                if replacement is not None:
                    return replacement
            raise

        if not getattr(settings, 'USE_CUSTOM_ERROR_PAGES', False):
            return response
        if response.status_code in ERROR_PAGES_STATUS_CODES:
            return render_error_page(request, response.status_code)
        return response

    def process_exception(self, request, exception):
        if not getattr(settings, 'USE_CUSTOM_ERROR_PAGES', False):
            return None
        return handle_exception_for_custom_page(request, exception)
