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

_DEBUG = '[EMPTY_MOVE_DEBUG]'


def _log_debug(step: str, **fields) -> None:
    """Console-visible debug line for empty-move create failures (grep EMPTY_MOVE_DEBUG)."""
    parts = [f'{_DEBUG} {step}']
    for key, value in fields.items():
        parts.append(f'{key}={value!r}')
    line = ' | '.join(parts)
    logger.warning(line)
    print(line, flush=True)


class EmptyMoveCreateAPIView(MobileAPIView):
    """
    Create an empty truck movement from the driver app (On Call mode).

    PCS §5.1: send ``empty_move_reason`` plus device GPS (``latitude`` /
    ``longitude`` or ``from_latitude`` / ``from_longitude``). Optional
    ``from_address`` may carry reverse-geocoded departure text. Arrival GPS is
    captured when the driver completes the move (workflow complete action).
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.empty_move'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [JSONParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = EmptyMoveCreateService()

    def post(self, request):
        _log_debug(
            'request_received',
            keys=sorted(request.data.keys()) if hasattr(request.data, 'keys') else type(request.data).__name__,
            reason=request.data.get('empty_move_reason'),
            has_from_uuid=bool(request.data.get('from_location_id')),
            has_to_uuid=bool(request.data.get('to_location_id')),
            has_from_address=bool(request.data.get('from_address')),
            has_to_address=bool(request.data.get('to_address')),
        )
        serializer = EmptyMoveCreateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            _log_debug('validation_failed', errors=dict(serializer.errors))
            return self.validation_error(serializer)

        tenant_schema = tenant_schema_for_request(request)
        jwt_payload = get_mobile_jwt_payload(request)
        tenant_user, driver, err_msg, err_code = resolve_mobile_driver_session(
            request,
            jwt_payload,
        )
        if driver is None:
            _log_debug(
                'driver_session_failed',
                err_code=err_code,
                err_msg=str(err_msg or ''),
                tenant_schema=tenant_schema,
            )
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        if not tenant_schema:
            _log_debug(
                'tenant_required',
                driver_id=getattr(driver, 'pk', ''),
                jwt_tenant=jwt_payload.get('tenant_schema') if jwt_payload else None,
            )
            return self.error(
                message=_('mobile.auth.tenant_required'),
                code='tenant_required',
                message_key='mobile.auth.tenant_required',
                http_code=400,
            )

        _log_debug(
            'create_start',
            tenant_schema=tenant_schema,
            driver_id=getattr(driver, 'pk', ''),
            driver_code=getattr(driver, 'driver_code', ''),
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
            _log_debug(
                'business_error',
                code=exc.code,
                http_status=exc.http_status,
                message=str(exc),
                message_key=exc.message_key,
            )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
                data=exc.data or None,
            )

        movement = data.get('empty_move') or {}
        _log_debug(
            'create_success',
            tenant_schema=tenant_schema,
            driver_id=getattr(driver, 'pk', ''),
            movement_id=movement.get('movement_id'),
            movement_no=movement.get('movement_no'),
            workflow_started=movement.get('workflow_started'),
        )

        return self.success(
            message=str(_('mobile.empty_move.create_success')),
            data=data,
            message_key='mobile.empty_move.create_success',
            http_code=201,
        )
