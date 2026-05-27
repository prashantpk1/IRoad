"""
mobile_api/payment_collection/views/payment_collection_view.py

POST payment collection evidence staging (prep-only).

``POST /api/v1/mobile/driver/payments/collect/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.job_detail.services.job_detail_driver_resolver import (
    tenant_schema_for_request,
)
from mobile_api.payment_collection.exceptions import PaymentCollectionError
from mobile_api.payment_collection.serializers.payment_collection_serializer import (
    PaymentCollectionRequestSerializer,
)
from mobile_api.payment_collection.services.payment_collection_service import (
    PaymentCollectionService,
)
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.payment_collection')


class PaymentCollectionAPIView(MobileAPIView):
    """Prep-only evidence staging for driver COD payment collection."""

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.payment_collection'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = PaymentCollectionService()

    def post(self, request):
        serializer = PaymentCollectionRequestSerializer(data=request.data)
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
            data = self._service.stage_payment(
                driver=driver,
                tenant_schema=tenant_schema,
                payload=serializer.validated_data,
            )
        except PaymentCollectionError as exc:
            return self.error(
                message=str(exc),
                code=exc.code,
                message_key=exc.message_key,
                http_code=exc.http_status,
            )

        logger.info(
            'payment_collect tenant=%s driver=%s shipment=%s client_payment_id=%s replayed=%s',
            tenant_schema,
            getattr(driver, 'pk', ''),
            data.get('payment_bundle', {}).get('shipment_id'),
            data.get('payment_bundle', {}).get('client_payment_id'),
            data.get('payment_bundle', {}).get('replayed'),
        )

        http_code = 201 if not data.get('payment_bundle', {}).get('replayed') else 200
        return self.success(
            message=str(_('mobile.payment_collection.submit_success')),
            data=data,
            message_key='mobile.payment_collection.submit_success',
            http_code=http_code,
        )

