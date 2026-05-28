"""
mobile_api/execution/views/execute_action_view.py

POST unified driver execute action by explicit ``job_type`` + ``job_id`` + ``action_code``.

``POST /api/v1/mobile/driver/jobs/<job_type>/<job_id>/actions/<action_code>/execute/``
"""
from __future__ import annotations

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext as _
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.serializers.execute_action_serializer import (
    ExecuteActionRequestSerializer,
    ExecuteActionResponseSerializer,
)
from mobile_api.execution.services.execute_action_orchestrator import (
    ExecuteActionOrchestrator,
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
from mobile_api.utils.file_upload_handler import process_media_files
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.execution')


class ExecuteActionAPIView(MobileAPIView):
    """
    Authoritative mobile workflow execution — frontend must not mutate workflow directly.

    Security: JWT (``IsMobileAuthenticated``), driver role, RBAC capability, tenant schema,
    object ownership + ``mobile_execution_guard`` inside orchestrator/kernel.
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.execute'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._orchestrator = ExecuteActionOrchestrator()

    def post(self, request, job_type: str, job_id: str, action_code: str):
        serializer_data = request.data
        if any(str(k).startswith('media[') for k in request.FILES.keys()):
            processed = process_media_files(
                request.FILES,
                request.data,
                subfolder='evidence',
            )
            if processed:
                merged_data = {k: request.data.get(k) for k in request.data.keys()}
                merged_data['media'] = processed
                serializer_data = merged_data

        serializer = ExecuteActionRequestSerializer(data=serializer_data)
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
            result = self._orchestrator.execute_driver_action(
                driver=driver,
                tenant=type('TenantRef', (), {'schema_name': tenant_schema})(),
                job_type=job_type,
                job_id=job_id,
                action_code=action_code,
                payload=serializer.validated_data,
                request=request,
                tenant_user=tenant_user,
                user_id=str(jwt_payload.get('user_id') or ''),
            )
        except ExecuteActionError as exc:
            logger.warning(
                'execute_action denied job_type=%s job_id=%s action=%s code=%s',
                job_type,
                job_id,
                action_code,
                exc.code,
            )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
                data=exc.to_validation_dict(),
            )
        except DjangoValidationError as exc:
            message = '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)
            logger.warning(
                'execute_action_kernel_error job_type=%s job_id=%s action=%s err=%s',
                job_type,
                job_id,
                action_code,
                message,
            )
            return self.error(
                message=message,
                code='execution_validation_failed',
                message_key='mobile.jobs.execute.execution_validation_failed',
                http_code=400,
            )

        response_serializer = ExecuteActionResponseSerializer(data=result.payload)
        response_serializer.is_valid(raise_exception=True)

        return self.success(
            message=_('mobile.success.action_executed'),
            data=response_serializer.validated_data,
            message_key='mobile.success.action_executed',
            http_code=result.http_status,
        )
