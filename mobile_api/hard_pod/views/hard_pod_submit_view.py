"""
mobile_api/hard_pod/views/hard_pod_submit_view.py

POST Hard POD custody submit (prepares custody — no workflow mutation).

``POST /api/v1/mobile/driver/hard-pod/submit/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.hard_pod.exceptions import HardPodError
from mobile_api.hard_pod.serializers.hard_pod_submit_serializer import (
    HardPodSubmitRequestSerializer,
)
from mobile_api.hard_pod.services.hard_pod_submit_service import HardPodSubmitService
from mobile_api.job_detail.services.job_detail_driver_resolver import tenant_schema_for_request
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.hard_pod')


class HardPodSubmitAPIView(MobileAPIView):
    """
    Submit Hard POD custody evidence for one shipment.

    Creates append-only custody events and immutable media rows.
    Does **not** execute workflow actions or update shipment status.
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.hard_pod'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = HardPodSubmitService()

    def post(self, request):
        serializer = HardPodSubmitRequestSerializer(data=request.data)
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
            data = self._service.submit_custody(
                driver=driver,
                tenant_schema=tenant_schema,
                payload=serializer.validated_data,
            )
        except HardPodError as exc:
            logger.warning(
                'hard_pod_submit denied code=%s shipment=%s',
                exc.code,
                serializer.validated_data.get('shipment_id'),
            )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        execute_step = data.get('execute_step') or {}
        if execute_step.get('error_code') and not execute_step.get('promoted'):
            return self.error(
                message=str(
                    execute_step.get('message')
                    or _('mobile.hard_pod.execute_failed'),
                ),
                code=str(execute_step.get('error_code') or 'hard_pod_execute_failed'),
                message_key=str(
                    execute_step.get('message_key') or 'mobile.hard_pod.execute_failed',
                ),
                http_code=400,
                data=data,
            )

        logger.info(
            'hard_pod_submit tenant=%s driver=%s submission=%s replayed=%s',
            tenant_schema,
            getattr(driver, 'pk', ''),
            data.get('custody_submission', {}).get('submission_id'),
            data.get('custody_submission', {}).get('replayed'),
        )
        return self.success(
            message=str(_('mobile.hard_pod.submit_success')),
            data=data,
            message_key='mobile.hard_pod.submit_success',
            http_code=201 if not data.get('custody_submission', {}).get('replayed') else 200,
        )
