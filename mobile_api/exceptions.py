"""
mobile_api/exceptions.py

Global exception handler for Mobile API.

Converts DRF exceptions into the unified envelope (see
``mobile_api.response_envelope`` and ``mobile_api/docs/API_RESPONSE_CONTRACT.md``).

Configured in REST_FRAMEWORK settings:
  'EXCEPTION_HANDLER': 'mobile_api.exceptions.mobile_exception_handler'
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
    NotFound,
    MethodNotAllowed,
    Throttled,
)
from rest_framework.response import Response
from rest_framework import status
from django.utils.translation import gettext as _

from mobile_api.response_envelope import (
    build_error_body,
    validation_error_body_from_drf,
    ensure_mobile_request_id,
)

logger = logging.getLogger('mobile_api')


def mobile_exception_handler(exc, context):
    """
    Custom exception handler for Mobile API.

    Auth exceptions → body ``status`` = 2, HTTP 401/403
    Validation → ``status`` = 0 + ``data.validation``
    Throttled → HTTP 429, ``code`` = ``rate_limited``
    """
    request = context.get('request')
    if request is not None:
        ensure_mobile_request_id(request)

    response = exception_handler(exc, context)

    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        account_deleted_msg = str(_('mobile.auth.account_deleted'))
        is_account_deleted = False
        if isinstance(exc, AuthenticationFailed):
            codes = exc.get_codes()
            if codes == 'account_deleted':
                is_account_deleted = True
            elif isinstance(codes, list) and 'account_deleted' in codes:
                is_account_deleted = True
        if is_account_deleted:
            body = build_error_body(
                app_status=2,
                message=account_deleted_msg,
                request=request,
                code='account_deleted',
                message_key='mobile.auth.account_deleted',
            )
            return Response(body, status=status.HTTP_401_UNAUTHORIZED)
        body = build_error_body(
            app_status=2,
            message=str(_('mobile.auth.unauthorized')),
            request=request,
            code='unauthorized',
            message_key='mobile.auth.unauthorized',
        )
        return Response(body, status=status.HTTP_401_UNAUTHORIZED)

    if isinstance(exc, PermissionDenied):
        body = build_error_body(
            app_status=2,
            message=str(_('mobile.auth.forbidden')),
            request=request,
            code='forbidden',
            message_key='mobile.auth.forbidden',
        )
        return Response(body, status=status.HTTP_403_FORBIDDEN)

    if isinstance(exc, ValidationError):
        body = validation_error_body_from_drf(
            message=str(_('mobile.validation.failed')),
            request=request,
            drf_detail=getattr(exc, 'detail', exc),
            message_key='mobile.validation.failed',
        )
        return Response(body, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, NotFound):
        body = build_error_body(
            app_status=0,
            message=str(_('mobile.error.not_found')),
            request=request,
            code='not_found',
            message_key='mobile.error.not_found',
        )
        return Response(body, status=status.HTTP_404_NOT_FOUND)

    if isinstance(exc, MethodNotAllowed):
        body = build_error_body(
            app_status=0,
            message=str(_('mobile.error.method_not_allowed')),
            request=request,
            code='method_not_allowed',
            message_key='mobile.error.method_not_allowed',
        )
        return Response(body, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    if isinstance(exc, Throttled):
        wait = exc.wait
        message = (
            str(_('mobile.error.rate_limit'))
            + (f' Try again in {int(wait)} seconds.' if wait else '')
        )
        details = {}
        if wait is not None:
            details['retry_after_seconds'] = int(wait)
        body = build_error_body(
            app_status=0,
            message=message,
            request=request,
            code='rate_limited',
            message_key='mobile.error.rate_limit',
            details=details,
        )
        return Response(body, status=status.HTTP_429_TOO_MANY_REQUESTS)

    if response is not None:
        status_code = response.status_code
        if status_code >= 500:
            message = str(_('mobile.error.server_error'))
            code = 'server_error'
            msg_key = 'mobile.error.server_error'
        else:
            message = str(_('mobile.error.generic'))
            code = 'error'
            msg_key = 'mobile.error.generic'
            if hasattr(exc, 'detail') and status_code < 500:
                detail = exc.detail
                if isinstance(detail, str) and detail.strip():
                    message = detail
                elif isinstance(detail, list) and detail:
                    message = str(detail[0])
                elif isinstance(detail, dict) and detail:
                    message = str(_('mobile.error.generic'))
        body = build_error_body(
            app_status=0,
            message=message,
            request=request,
            code=code,
            message_key=msg_key,
        )
        return Response(body, status=status_code)

    logger.exception(
        'Unhandled Mobile API exception: %s',
        exc.__class__.__name__,
        extra={
            'view': context.get('view'),
            'request': context.get('request'),
        },
    )
    body = build_error_body(
        app_status=0,
        message=str(_('mobile.error.server_error')),
        request=request,
        code='server_error',
        message_key='mobile.error.server_error',
    )
    return Response(body, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
