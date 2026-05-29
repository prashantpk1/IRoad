"""
mobile_api/wallet/views/wallet_list_view.py

GET driver My Wallet summary + recent transactions.

``GET /api/v1/mobile/driver/wallet/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.job_detail.services.job_detail_driver_resolver import (
    resolve_job_detail_driver,
    tenant_schema_for_request,
)
from mobile_api.list_pagination import parse_list_pagination
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.wallet.exceptions import WalletError
from mobile_api.wallet.serializers.wallet_serializer import WalletListResponseSerializer
from mobile_api.wallet.services.wallet_service import WalletService

logger = logging.getLogger('mobile_api.wallet')


class WalletListAPIView(MobileAPIView):
    """
    My Wallet tab — treasury balance + transaction list (read-only).

    Query parameters:
      - ``shipment_no`` — filter by shipment number (partial) or transaction no
      - ``date`` — transaction date (``YYYY-MM-DD`` or ``DD-MM-YYYY``)
      - ``count_only`` — filter modal preview (`results_found` only)
      - ``page`` — page number (default ``1``)
      - ``page_size`` — rows per page (default ``10``, max ``100``)
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.wallet'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = WalletService()

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
            page = self._service.list_wallet(
                driver,
                tenant_schema=tenant_schema,
                shipment_no=request.query_params.get('shipment_no'),
                transaction_date=request.query_params.get('date'),
                count_only=count_only,
                pagination=parse_list_pagination(
                    request.query_params.get('page'),
                    request.query_params.get('page_size'),
                ),
            )
        except WalletError as exc:
            logger.warning('wallet_list denied code=%s', exc.code)
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        payload = {
            'summary': page.summary,
            'items': page.items,
            'count': page.count,
            'results_found': page.results_found,
            'total_records': page.total_records,
            'total_pages': page.total_pages,
            'current_page': page.current_page,
            'page_size': page.page_size,
        }
        serializer = WalletListResponseSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
        )
