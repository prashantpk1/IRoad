"""
POST driver-initiated empty move creation.

``POST /api/v1/mobile/driver/empty-moves/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _
from rest_framework.parsers import JSONParser

from mobile_api.empty_move.exceptions import EmptyMoveError
from mobile_api.empty_move.serializers.empty_move_create_serializer import (
    EmptyMoveCreateRequestSerializer,
)
from mobile_api.empty_move.services.empty_move_create_service import (
    EmptyMoveCreateService,
)
from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.job_detail.services.job_detail_driver_resolver import (
    tenant_schema_for_request,
)
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.empty_move')


class EmptyMoveCreateAPIView(MobileAPIView):
    """
    Create an empty truck movement from the driver app (On Call mode).

    Does not require Google Maps Geocoding — ``from_location_id`` / ``to_location_id``
    are tenant location master UUIDs. Optional ``from_latitude`` / ``from_longitude``
    and ``to_latitude`` / ``to_longitude`` stamp the TML route map links; start GPS
    is always attached to EM1, which fires automatically on create.
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.empty_move'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [JSONParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = EmptyMoveCreateService()

    def post(self, request):
        serializer = EmptyMoveCreateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        tenant_schema = tenant_schema_for_request(request)
        jwt_payload = get_mobile_jwt_payload(request)
        tenant_user, driver, err_msg, err_code = resolve_mobile_driver_session(
            request,
            jwt_payload,
        )
        if driver is None:
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        if not tenant_schema:
            return self.error(
                message=_('mobile.auth.tenant_required'),
                code='tenant_required',
                message_key='mobile.auth.tenant_required',
                http_code=400,
            )

        try:
            data = self._service.create_empty_move(
                driver=driver,
                tenant_user=tenant_user,
                tenant_schema=tenant_schema,
                payload=serializer.validated_data,
                request=request,
                jwt_payload=jwt_payload,
            )
        except EmptyMoveError as exc:
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        movement = data.get('empty_move') or {}
        logger.info(
            'empty_move_create tenant=%s driver=%s movement=%s started=%s',
            tenant_schema,
            getattr(driver, 'pk', ''),
            movement.get('movement_id'),
            movement.get('workflow_started'),
        )

        return self.success(
            message=str(_('mobile.empty_move.create_success')),
            data=data,
            message_key='mobile.empty_move.create_success',
            http_code=201,
        )
