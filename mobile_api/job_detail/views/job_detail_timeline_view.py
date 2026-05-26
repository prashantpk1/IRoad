"""
mobile_api/job_detail/views/job_detail_timeline_view.py

GET paginated Action Log timeline for an explicit job.
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _
from rest_framework.request import Request

from mobile_api.job_detail.exceptions import JobDetailError
from mobile_api.job_detail.serializers.job_detail_timeline_serializer import (
    JobDetailTimelinePageSerializer,
)
from mobile_api.job_detail.services.job_detail_driver_resolver import (
    resolve_job_detail_driver,
    tenant_schema_for_request,
)
from mobile_api.job_detail.services.job_detail_timeline_api_service import (
    JobDetailTimelineApiService,
)
from mobile_api.job_detail.timeline.timeline_service import JobDetailTimelineService
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.views.driver_profile import _mobile_user_id

logger = logging.getLogger('mobile_api.job_detail.timeline')


class JobDetailTimelineAPIView(MobileAPIView):
    """
    GET /api/v1/mobile/driver/jobs/<job_type>/<job_id>/timeline/

    Query params:
      - ``cursor`` — opaque keyset token (older page)
      - ``limit`` — page size (bounded by settings)

    Timeline-only: no workflow / POD/COD / reconcile.
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
        self._timeline_api_service = JobDetailTimelineApiService()

    def get(self, request: Request, job_type: str, job_id: str):
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

        cursor = (request.query_params.get('cursor') or '').strip() or None
        raw_limit = request.query_params.get('limit')
        if raw_limit not in (None, ''):
            try:
                limit = JobDetailTimelineService.clamp_page_limit(int(raw_limit))
            except (TypeError, ValueError):
                limit = JobDetailTimelineService.clamp_page_limit(None)
        else:
            limit = None

        try:
            payload = self._timeline_api_service.fetch_timeline_page(
                driver,
                job_type,
                job_id,
                tenant_schema=tenant_schema,
                user_id=user_id,
                cursor=cursor,
                limit=limit,
                request=request,
            )
        except JobDetailError as exc:
            logger.warning(
                'job_detail_timeline denied job_type=%s job_id=%s code=%s',
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
            return self.error(
                message=str(exc),
                code='invalid_job_reference',
                message_key='mobile.validation.failed',
                http_code=400,
            )

        serializer = JobDetailTimelinePageSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        self.log_info(
            'driver_job_detail_timeline',
            job_type=job_type,
            job_id=job_id,
            has_more=serializer.validated_data.get('has_more'),
        )

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
        )
