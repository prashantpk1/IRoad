"""
mobile_api/job_detail/views/job_detail_view.py

GET unified driver job detail by explicit ``job_type`` + ``job_id``.
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _
from rest_framework import status as http_status
from rest_framework.response import Response

from mobile_api.job_detail.exceptions import JobDetailError
from mobile_api.job_detail.serializers.job_detail_serializer import (
    JobDetailResponseSerializer,
)
from mobile_api.job_detail.services.job_detail_context_service import (
    JobDetailContextService,
)
from mobile_api.job_detail.services.job_detail_driver_resolver import (
    resolve_job_detail_driver,
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

logger = logging.getLogger('mobile_api.job_detail')


class JobDetailAPIView(MobileAPIView):
    """
    GET /api/v1/mobile/driver/jobs/<job_type>/<job_id>/

    Explicit job execution screen — not current-job selection.

    Supports ``If-None-Match`` / ``ETag`` for polling (304 when unchanged).
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.job_detail'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._context_service = JobDetailContextService()

    def get(self, request, job_type: str, job_id: str):
        tenant_schema = tenant_schema_for_request(request)
        user_id = _mobile_user_id(request)

        driver, err_msg, err_code = resolve_job_detail_driver(request)
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
            result = self._context_service.resolve_job_detail(
                driver,
                job_type,
                job_id,
                tenant_schema=tenant_schema,
                user_id=user_id,
                jwt_payload=_mobile_jwt_payload(request),
                request=request,
            )
        except JobDetailError as exc:
            logger.warning(
                'job_detail denied job_type=%s job_id=%s code=%s',
                job_type,
                job_id,
                exc.code,
            )
            if exc.http_status == 404:
                return self.error(
                    message=str(exc),
                    code=exc.code,
                    message_key=exc.message_key,
                    http_code=404,
                )
            if exc.http_status == 403:
                return self.error(
                    message=str(exc),
                    code=exc.code,
                    message_key=exc.message_key,
                    http_code=403,
                )
            if exc.http_status == 401:
                return self.auth_error(
                    message=str(exc),
                    code=exc.code,
                    message_key=exc.message_key,
                )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )
        except ValueError as exc:
            logger.warning(
                'job_detail bad_request job_type=%s job_id=%s err=%s',
                job_type,
                job_id,
                exc,
            )
            return self.error(
                message=str(exc),
                code='invalid_job_reference',
                message_key='mobile.validation.failed',
                http_code=400,
            )

        if result.not_modified:
            response = Response(status=http_status.HTTP_304_NOT_MODIFIED)
            if result.etag:
                response['ETag'] = result.etag
            return response

        payload = self._context_service.build_api_payload(
            result.context,
            request=request,
        )
        serializer = JobDetailResponseSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        self.log_info(
            'driver_job_detail',
            job_type=job_type,
            job_id=job_id,
        )

        http_response = self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
            meta_extra={
                'content_hash': result.context.content_hash,
            },
        )
        if result.etag:
            http_response['ETag'] = result.etag
        return http_response
