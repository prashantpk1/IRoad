"""
mobile_api/history/views/history_detail_view.py

GET read-only History Detail for one completed shipment.

``GET /api/v1/mobile/driver/history/<shipment_id>/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.history.exceptions import HistoryError
from mobile_api.history.serializers.history_serializer import HistoryDetailResponseSerializer
from mobile_api.history.services.history_service import HistoryService
from mobile_api.job_detail.services.job_detail_driver_resolver import (
    resolve_job_detail_driver,
    tenant_schema_for_request,
)
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.history')


class HistoryDetailAPIView(MobileAPIView):
    """
    History Detail — read-only audit trail (Action Log + evidence).

    Per IRoute §14.7.1: every forward action with timestamps, GPS, and media.
    Does **not** accept mutations (no execute / stage APIs).
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.history'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = HistoryService()

    def get(self, request, shipment_id: str):
        driver, err_msg, err_code = resolve_job_detail_driver(request)
        if driver is None:
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        tenant_schema = tenant_schema_for_request(request)

        try:
            payload = self._service.get_history_detail(
                driver,
                shipment_id,
                tenant_schema=tenant_schema,
                request=request,
            )
        except HistoryError as exc:
            logger.warning(
                'history_detail denied shipment_id=%s code=%s',
                shipment_id,
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
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        serializer = HistoryDetailResponseSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
        )
