"""
mobile_api/dashboard/views/dashboard_view.py

GET unified driver dashboard.
"""
from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _
from rest_framework import status as http_status
from rest_framework.response import Response

from mobile_api.dashboard.serializers.dashboard_serializer import (
    DashboardResponseSerializer,
)
from mobile_api.dashboard.services.dashboard_context_service import (
    DashboardContextService,
)
from mobile_api.dashboard.services.driver_resolver import (
    resolve_dashboard_driver,
    tenant_schema_for_request,
)
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.views.driver_profile import (
    _mobile_jwt_payload,
    _mobile_user_id,
)

logger = logging.getLogger('mobile_api.dashboard')


class DashboardAPIView(MobileAPIView):
    """
    GET /api/v1/mobile/driver/dashboard/

    Supports ``ETag`` / ``If-None-Match`` for polling (304 when unchanged).
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.dashboard'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._context_service = DashboardContextService()

    def get(self, request):
        tenant_schema = tenant_schema_for_request(request)
        user_id = _mobile_user_id(request)

        driver, err_msg, err_code = resolve_dashboard_driver(request)
        if driver is None:
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        try:
            result = self._context_service.resolve_driver_dashboard(
                driver,
                tenant_schema=tenant_schema,
                user_id=user_id,
                jwt_payload=_mobile_jwt_payload(request),
                request=request,
            )
        except PermissionDenied:
            logger.warning(
                'dashboard ownership denied user_id=%s schema=%s',
                user_id,
                tenant_schema,
            )
            return self.error(
                message=_('mobile.auth.forbidden'),
                code='forbidden',
                message_key='mobile.auth.forbidden',
                http_code=403,
            )

        if result.not_modified:
            response = Response(status=http_status.HTTP_304_NOT_MODIFIED)
            if result.etag:
                response['ETag'] = result.etag
            return response

        context = result.context
        payload = self._context_service.build_api_payload(
            context,
            request=request,
        )

        serializer = DashboardResponseSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        self.log_info(
            'driver_dashboard',
            booking=bool(context.active_booking),
            shipment=bool(context.active_shipment),
            empty_move=bool(context.active_empty_movement),
        )

        http_response = self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
            meta_extra={
                'content_hash': context.content_hash,
            },
        )
        if result.etag:
            http_response['ETag'] = result.etag
        return http_response
