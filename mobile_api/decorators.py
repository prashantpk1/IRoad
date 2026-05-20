"""
mobile_api/decorators.py

Non-DRF entrypoints (function-based views, webhooks) can wrap handlers with
capability checks. **Prefer** DRF ``permission_classes`` + ``HasViewMobileCapability``
on ``APIView`` subclasses (used consistently on driver profile / org / session APIs).

``require_mobile_capability`` is an alias of ``mobile_capability_required`` for
clearer imports in security-sensitive modules.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from django.http import JsonResponse
from django.utils.translation import gettext as _

from mobile_api.rbac import request_has_capability

F = TypeVar('F', bound=Callable[..., Any])


def mobile_capability_required(capability_id: str) -> Callable[[F], F]:
    """
    Deny with JSON envelope ``{status:0, ...}`` when the principal lacks capability.

    Example::

        @mobile_capability_required('mobile.operations.read')
        def my_fbv(request):
            ...
    """

    def decorator(view_func: F) -> F:
        @functools.wraps(view_func)
        def _wrapped(request: Any, *args: Any, **kwargs: Any):
            if not request_has_capability(request, capability_id):
                return JsonResponse(
                    {
                        'status': 0,
                        'message': str(_('mobile.auth.capability_denied')),
                        'data': {
                            'error_code': 'capability_denied',
                            'capability': capability_id,
                        },
                    },
                    status=403,
                )
            return view_func(request, *args, **kwargs)

        return _wrapped  # type: ignore[return-value]

    return decorator


# Enterprise-friendly alias (same behaviour).
require_mobile_capability = mobile_capability_required
