"""
GET serviceable locations for empty move pickup/delivery pickers.

``GET /api/v1/mobile/driver/empty-moves/locations/``
"""
from __future__ import annotations

from django.utils.translation import gettext as _

from mobile_api.empty_move.services.empty_move_locations_service import (
    EmptyMoveLocationsService,
)
from mobile_api.helpers.mobile_driver_session import resolve_mobile_driver_session
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
from mobile_api.views.base import MobileAPIView


class EmptyMoveLocationsAPIView(MobileAPIView):
    """
    Return active, serviceable Location Master rows.

    Mobile must send ``location_id`` (UUID) from this list as
    ``from_location_id`` / ``to_location_id`` on empty move create — not map
    place numeric IDs.
    """

    permission_classes = [IsMobileAuthenticated, IsDriver, HasViewMobileCapability]
    required_mobile_capability = 'mobile.driver.empty_move'
    throttle_classes = [MobileUserThrottle]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._service = EmptyMoveLocationsService()

    def get(self, request):
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

        search = (request.query_params.get('search') or '').strip()
        try:
            limit = int(request.query_params.get('limit') or 100)
        except (TypeError, ValueError):
            limit = 100

        data = self._service.list_locations(
            tenant_schema=tenant_schema,
            request=request,
            search=search,
            limit=limit,
        )
        return self.success(
            message=str(_('mobile.success.data_retrieved')),
            data=data,
            message_key='mobile.success.data_retrieved',
        )
