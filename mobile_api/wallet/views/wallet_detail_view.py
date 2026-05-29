"""
mobile_api/wallet/views/wallet_detail_view.py

GET read-only transaction detail for My Wallet.

``GET /api/v1/mobile/driver/wallet/transactions/<transaction_id>/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.job_detail.services.job_detail_driver_resolver import (
    resolve_job_detail_driver,
    tenant_schema_for_request,
)
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView
from mobile_api.wallet.exceptions import WalletError
from mobile_api.wallet.serializers.wallet_serializer import WalletDetailResponseSerializer
from mobile_api.wallet.services.wallet_service import WalletService

logger = logging.getLogger('mobile_api.wallet')


class WalletTransactionDetailAPIView(MobileAPIView):
    """
    Transaction Details — read-only COD treasury row + linked shipment context.

    ``transaction_id`` accepts UUID or ``transaction_no`` (e.g. ``TT-000123``).
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.wallet'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = WalletService()

    def get(self, request, transaction_id: str):
        driver, err_msg, err_code = resolve_job_detail_driver(request)
        if driver is None:
            return self.auth_error(
                message=str(err_msg or _('mobile.auth.unauthorized')),
                code=str(err_code or 'unauthorized'),
                message_key='mobile.auth.unauthorized',
            )

        tenant_schema = tenant_schema_for_request(request)

        try:
            payload = self._service.get_transaction_detail(
                driver,
                transaction_id,
                tenant_schema=tenant_schema,
            )
        except WalletError as exc:
            logger.warning(
                'wallet_detail denied transaction_id=%s code=%s',
                transaction_id,
                exc.code,
            )
            if exc.http_status == 404:
                return self.error(
                    message=str(exc),
                    code=exc.code,
                    message_key=exc.message_key,
                    http_code=404,
                )
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        serializer = WalletDetailResponseSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=serializer.validated_data,
            message_key='mobile.success.data_retrieved',
        )
