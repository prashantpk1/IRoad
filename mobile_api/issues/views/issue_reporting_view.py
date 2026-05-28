"""
mobile_api/issues/views/issue_reporting_view.py

POST operational issue / delay reporting (prep-only).

``POST /api/v1/mobile/driver/issues/report/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.issues.exceptions import IssueReportingError
from mobile_api.issues.serializers.issue_reporting_serializer import (
    IssueReportingRequestSerializer,
)
from mobile_api.issues.services.issue_reporting_service import IssueReportingService
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

logger = logging.getLogger('mobile_api.issues')


class IssueReportingAPIView(MobileAPIView):
    """Prep-only operational exception reporting for drivers."""

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.issues'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = IssueReportingService()

    def post(self, request):
        serializer_data = request.data
        if any(str(k).startswith('media[') for k in request.FILES.keys()):
            processed = process_media_files(
                request.FILES,
                request.data,
                subfolder='issue_evidence',
            )
            if processed:
                merged_data = {k: request.data.get(k) for k in request.data.keys()}
                merged_data['media'] = processed
                serializer_data = merged_data

        serializer = IssueReportingRequestSerializer(data=serializer_data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        tenant_schema = tenant_schema_for_request(request)
        jwt_payload = get_mobile_jwt_payload(request)
        _tenant_user, driver, err_msg, err_code = resolve_mobile_driver_session(
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
            data = self._service.report_issue(
                driver=driver,
                tenant_schema=tenant_schema,
                payload=serializer.validated_data,
            )
        except IssueReportingError as exc:
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        logger.info(
            'issue_report tenant=%s driver=%s shipment=%s client_issue_id=%s type=%s replayed=%s',
            tenant_schema,
            getattr(driver, 'pk', ''),
            data.get('issue', {}).get('shipment_id'),
            data.get('issue', {}).get('client_issue_id'),
            data.get('issue', {}).get('issue_type'),
            data.get('issue', {}).get('replayed'),
        )

        http_code = 201 if not data.get('issue', {}).get('replayed') else 200
        return self.success(
            message=str(_('mobile.issues.report_success')),
            data=data,
            message_key='mobile.issues.report_success',
            http_code=http_code,
        )
