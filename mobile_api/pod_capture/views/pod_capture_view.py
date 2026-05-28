"""
mobile_api/pod_capture/views/pod_capture_view.py

POST shipment POD evidence capture (staging only).

``POST /api/v1/mobile/driver/jobs/shipments/<shipment_id>/pod/capture/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.job_detail.services.job_detail_driver_resolver import tenant_schema_for_request
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.pod_capture.exceptions import PodCaptureError
from mobile_api.pod_capture.serializers.pod_capture_serializer import (
    PodCaptureRequestSerializer,
)
from mobile_api.pod_capture.services.pod_capture_orchestrator import PodCaptureOrchestrator
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.utils.file_upload_handler import process_media_files
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.pod_capture')


class PodCaptureAPIView(MobileAPIView):
    """
    Stage POD evidence for a shipment — does not execute workflow actions.

    Security: JWT, driver role, ``mobile.driver.pod_capture``, tenant schema,
    shipment ownership inside orchestrator.
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.pod_capture'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._orchestrator = PodCaptureOrchestrator()

    def post(self, request, shipment_id: str):
        if any(str(k).startswith('media[') for k in request.FILES.keys()):
            processed = process_media_files(
                request.FILES,
                request.data,
                subfolder='pod_evidence',
            )
            if processed:
                data = request.data.copy()
                data['media'] = processed
                request._full_data = data

        serializer = PodCaptureRequestSerializer(data=request.data)
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
            data = self._orchestrator.capture_pod_evidence(
                driver=driver,
                tenant_schema=tenant_schema,
                shipment_id=shipment_id,
                payload=serializer.validated_data,
                request=request,
                user_id=str(jwt_payload.get('user_id') or ''),
                job_type='shipment',
            )
        except PodCaptureError as exc:
            logger.warning(
                'pod_capture denied shipment_id=%s code=%s',
                shipment_id,
                exc.code,
            )
            if exc.validation_error:
                return self.error(
                    message=str(exc),
                    data=exc.to_validation_dict(),
                    code=exc.code,
                    message_key=exc.message_key,
                    http_code=exc.http_status,
                )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        http_code = 200 if data.get('capture_bundle', {}).get('replayed') else 201
        return self.success(
            message=_('mobile.pod_capture.success'),
            data=data,
            message_key='mobile.pod_capture.success',
            http_code=http_code,
        )
