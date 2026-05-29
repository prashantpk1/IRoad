"""
mobile_api/history/views/history_list_view.py

GET driver completed-job history list with optional filters.

``GET /api/v1/mobile/driver/history/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.history.exceptions import HistoryError
from mobile_api.history.serializers.history_serializer import HistoryListResponseSerializer
from mobile_api.history.services.history_service import HistoryService
from mobile_api.job_detail.services.job_detail_driver_resolver import (
    resolve_job_detail_driver,
    tenant_schema_for_request,
)
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.history')


class HistoryListAPIView(MobileAPIView):
    """
    Driver History tab — completed terminal shipments (read-only).

    Query parameters:
      - ``shipment_no`` — partial or exact shipment number filter
      - ``date`` — job/shipment date (``YYYY-MM-DD`` or ``DD-MM-YYYY``)
      - ``count_only`` — when ``1``/``true``, return ``results_found`` only (filter preview)

    Returns the full filtered list in one response (no pagination).
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.history'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = HistoryService()

    def get(self, request):
        driver, err_msg, err_code = resolve_job_detail_driver(request)
        if driver is None:
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        tenant_schema = tenant_schema_for_request(request)
        count_only_raw = (request.query_params.get('count_only') or '').strip().casefold()
        count_only = count_only_raw in {'1', 'true', 'yes', 'on'}

        try:
            page = self._service.list_history(
                driver,
                tenant_schema=tenant_schema,
                shipment_no=request.query_params.get('shipment_no'),
                job_date=request.query_params.get('date'),
                count_only=count_only,
                request=request,
            )
        except HistoryError as exc:
            logger.warning('history_list denied code=%s', exc.code)
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        payload = {
            'items': page.items,
            'count': page.count,
            'results_found': page.results_found,
        }
        serializer = HistoryListResponseSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
        )
