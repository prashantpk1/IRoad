"""
mobile_api/views/base.py

Base APIView for all Mobile API endpoints.

Every mobile API view should extend MobileAPIView instead
of directly extending APIView. This ensures:
  1. Language activated from request header on every request
  2. Request logging for debugging
  3. Helper methods available (success, error, paginate)
  4. Unified response envelope (``meta``, ``message_key``, structured errors)

See ``mobile_api/docs/API_RESPONSE_CONTRACT.md`` and ``mobile_api.response_envelope``.
"""
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status

from mobile_api.helpers.i18n import activate_request_language
from mobile_api.pagination import MobileApiPagination
from mobile_api.response_envelope import (
    build_success_body,
    build_error_body,
    validation_error_body_from_drf,
    ensure_mobile_request_id,
)

logger = logging.getLogger('mobile_api')


class MobileAPIView(APIView):
    """
    Base class for all Mobile API views.

    Provides:
    - Language activation on every request
    - Unified JSON envelope (success / error / auth_error / validation_error)
    - Pagination helper
    - Request logging
    """

    def initialize_request(self, request, *args, **kwargs):
        """Activate language before any view logic runs."""
        result = super().initialize_request(
            request, *args, **kwargs
        )
        return result

    def initial(self, request, *args, **kwargs):
        """Called before dispatch — activate i18n and assign ``request_id``."""
        super().initial(request, *args, **kwargs)
        activate_request_language(request)
        ensure_mobile_request_id(request)

    # ── Response helpers ──────────────────────────────────────────

    def success(
        self,
        message: str,
        data=None,
        http_code: int = http_status.HTTP_200_OK,
        *,
        message_key: str | None = None,
        meta_extra: dict | None = None,
    ) -> Response:
        """Return a success response with ``status`` = 1 and ``meta``."""
        body = build_success_body(
            message=str(message),
            data=data if data is not None else {},
            request=self.request,
            message_key=message_key,
            meta_extra=meta_extra,
        )
        return Response(body, status=http_code)

    def error(
        self,
        message: str,
        data=None,
        http_code: int = http_status.HTTP_400_BAD_REQUEST,
        *,
        code: str = 'error',
        message_key: str | None = None,
        details: dict | None = None,
        validation_fields: dict | None = None,
        meta_extra: dict | None = None,
    ) -> Response:
        """
        Return a business/client error with ``status`` = 0.

        ``code`` is the canonical machine-readable code (also exposed as
        ``data.error_code`` for legacy clients).
        """
        body = build_error_body(
            app_status=0,
            message=str(message),
            request=self.request,
            code=code,
            message_key=message_key,
            data=data,
            details=details,
            validation_fields=validation_fields,
            meta_extra=meta_extra,
        )
        return Response(body, status=http_code)

    def auth_error(
        self,
        message: str,
        data=None,
        *,
        code: str = 'unauthorized',
        message_key: str | None = None,
        details: dict | None = None,
        meta_extra: dict | None = None,
    ) -> Response:
        """Return an auth/session error with ``status`` = 2 (HTTP 401)."""
        body = build_error_body(
            app_status=2,
            message=str(message),
            request=self.request,
            code=code,
            message_key=message_key,
            data=data,
            details=details,
            validation_fields=None,
            meta_extra=meta_extra,
        )
        return Response(body, status=http_status.HTTP_401_UNAUTHORIZED)

    def not_found(self, message: str, *, message_key: str | None = None) -> Response:
        """Return HTTP 404 with ``status`` = 0."""
        body = build_error_body(
            app_status=0,
            message=str(message),
            request=self.request,
            code='not_found',
            message_key=message_key,
            data=None,
            details={},
            validation_fields=None,
        )
        return Response(body, status=http_status.HTTP_404_NOT_FOUND)

    def validation_error(
        self,
        serializer,
        *,
        message=None,
        message_key: str = 'mobile.validation.failed',
    ) -> Response:
        """DRF serializer invalid → standard ``validation_failed`` envelope."""
        from django.utils.translation import gettext as _

        msg = str(message) if message is not None else str(_('mobile.validation.failed'))
        body = validation_error_body_from_drf(
            message=msg,
            request=self.request,
            drf_detail=serializer.errors,
            message_key=message_key,
        )
        return Response(body, status=http_status.HTTP_400_BAD_REQUEST)

    # ── Pagination helper ─────────────────────────────────────────

    def paginate(
        self,
        queryset,
        serializer_class,
        message: str = 'Data retrieved successfully',
        serializer_kwargs: dict = None,
    ) -> Response:
        """
        Paginate a queryset and return standard envelope.

        Args:
            queryset: Django QuerySet to paginate
            serializer_class: DRF Serializer class
            message: Success message string
            serializer_kwargs: Extra kwargs for serializer

        Returns:
            Paginated Response with standard envelope
        """
        paginator = MobileApiPagination()
        page = paginator.paginate_queryset(
            queryset, self.request
        )

        kwargs = serializer_kwargs or {}
        kwargs['many'] = True

        if page is not None:
            serializer = serializer_class(page, **kwargs)
            return paginator.get_paginated_response(
                serializer.data,
                message=message,
            )

        # No pagination — return all
        serializer = serializer_class(queryset, **kwargs)
        return self.success(message=message, data=serializer.data)

    # ── Language helper ───────────────────────────────────────────

    def get_language(self) -> str:
        """Get currently activated language code."""
        from mobile_api.helpers.i18n import get_request_language
        return get_request_language(self.request)

    # ── Logging helpers ───────────────────────────────────────────

    def log_info(self, message: str, **kwargs):
        logger.info(
            '[MobileAPI] %s | user=%s | schema=%s | %s',
            message,
            getattr(
                getattr(self.request, 'user', None),
                'user_id', 'anon'
            ),
            getattr(
                getattr(self.request, 'user', None),
                'tenant_schema', '-'
            ),
            kwargs,
        )

    def log_error(self, message: str, **kwargs):
        logger.error(
            '[MobileAPI] ERROR %s | user=%s | %s',
            message,
            getattr(
                getattr(self.request, 'user', None),
                'user_id', 'anon'
            ),
            kwargs,
        )
