"""
mobile_api/hard_pod/views/hard_pod_list_view.py

GET pending Hard POD custody queue (read-only).

``GET /api/v1/mobile/driver/hard-pod/pending/``
"""
from __future__ import annotations

import logging

from django.utils.translation import gettext as _

from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
from mobile_api.job_detail.services.job_detail_driver_resolver import tenant_schema_for_request
from mobile_api.permissions import HasViewMobileCapability, IsDriver, IsMobileAuthenticated
from mobile_api.hard_pod.serializers.hard_pod_list_serializer import HardPodListQuerySerializer
from mobile_api.hard_pod.services.hard_pod_list_service import HardPodListService
from mobile_api.rbac import get_mobile_jwt_payload
from mobile_api.throttling import MobileUserThrottle
from mobile_api.views.base import MobileAPIView

logger = logging.getLogger('mobile_api.hard_pod')


class HardPodListAPIView(MobileAPIView):
    """
    List pending Hard POD collections for the authenticated driver.

    Custody projection only — does not execute workflow actions or mutate shipments.
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
        self._service = HardPodListService()

    def get(self, request):
        query = HardPodListQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return self.validation_error(query)

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

        payload = self._service.list_pending(
            driver=driver,
            tenant_schema=tenant_schema,
        )

        if payload.get('error'):
            code = str(payload.get('code') or 'hard_pod_error')
            return self.error(
                message=_('mobile.hard_pod.list_failed'),
                code=code,
                message_key=str(payload.get('message_key') or 'mobile.hard_pod.list_failed'),
                http_code=400 if code == 'tenant_required' else 403,
            )

        limit = int(query.validated_data.get('limit') or 50)
        items = list(payload.get('items') or [])[:limit]

        logger.info(
            'hard_pod_list tenant=%s driver=%s count=%s',
            tenant_schema,
            getattr(driver, 'pk', ''),
            len(items),
        )
        return self.success(
            message=str(_('mobile.success.data_retrieved')),
            data={
                'items': items,
                'count': len(items),
            },
            message_key='mobile.success.data_retrieved',
        )
