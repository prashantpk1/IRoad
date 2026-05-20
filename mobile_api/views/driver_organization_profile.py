"""
mobile_api/views/driver_organization_profile.py

GET organization / support snapshot for the authenticated driver.

Developer notes: ``mobile_api/docs/driver_organization_profile.md``
"""
from django.utils.translation import gettext as _

from mobile_api.views.base import MobileAPIView
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.throttling import MobileUserThrottle
from mobile_api.services.driver_organization_profile_service import (
    get_driver_organization_profile,
)
from mobile_api.views.driver_profile import (
    _mobile_jwt_payload,
    _mobile_tenant_schema,
    _mobile_user_id,
)


class DriverOrganizationProfileView(MobileAPIView):
    """
    GET /api/v1/mobile/driver/organization-profile/

    Response ``data`` is built by ``DriverOrganizationProfileSerializer``:

    - ``organization_name``: from ``name_en`` / ``name_ar`` using ``Accept-Language``
      (``ar`` → Arabic with English fallback; otherwise English with Arabic fallback;
      missing/unsupported header → English-side rules per ``get_request_language``).
    - ``driver_instructions``: single DB column; same string for all languages.
    - ``logo_url``: absolute URL or empty string when no file.
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.organization'
    throttle_classes = [MobileUserThrottle]

    def get(self, request):
        result = get_driver_organization_profile(
            tenant_schema=_mobile_tenant_schema(request),
            user_id=_mobile_user_id(request),
            request=request,
            jwt_payload=_mobile_jwt_payload(request),
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='organization_profile_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_('mobile.success.data_retrieved'),
            data=result.get('organization_profile') or {},
            message_key='mobile.success.data_retrieved',
        )
