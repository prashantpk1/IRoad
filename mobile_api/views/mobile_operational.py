"""
mobile_api/views/mobile_operational.py

Operational (dispatcher / tenant-admin) mobile surfaces.

These endpoints are **not** driver-self-service; they use capability
``mobile.operations.read`` by default. Register additional views here and map
capabilities in ``mobile_api.rbac.CAPABILITY_GROUPS`` (or register at runtime via
``register_mobile_capability``).
"""
from django.utils.translation import gettext as _

from mobile_api.views.base import MobileAPIView
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsMobileAuthenticated,
)
from mobile_api.throttling import MobileUserThrottle


class MobileOperationalHealthView(MobileAPIView):
    """
    GET /api/v1/mobile/operational/health/

    Lightweight RBAC smoke check for operational principals (dispatcher or
    tenant admin). Drivers receive ``403`` unless they also satisfy dispatcher
    or admin role mapping (normally they do not).
    """

    permission_classes = [IsMobileAuthenticated, HasViewMobileCapability]
    required_mobile_capability = 'mobile.operations.read'
    throttle_classes = [MobileUserThrottle]

    def get(self, request):
        return self.success(
            message=_('mobile.success.data_retrieved'),
            data={
                'service': 'mobile_operational',
                'status': 'ok',
            },
        )
