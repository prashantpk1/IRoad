"""
mobile_api/views/driver_profile.py

Authenticated driver profile and change-password endpoints.

Views validate input, call services, and return MobileAPIView envelopes only.
"""
from django.utils.translation import gettext as _

from rest_framework.parsers import FormParser, MultiPartParser

from mobile_api.views.base import MobileAPIView
from mobile_api.permissions import (
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.throttling import (
    MobileAuthThrottle,
    MobileOtpThrottle,
    MobileUserThrottle,
)
from mobile_api.serializers.driver_profile import (
    DriverChangePasswordSerializer,
    DriverProfilePhotoUpdateSerializer,
    DriverProfileUpdateSerializer,
    DriverRequestChangePasswordOtpSerializer,
    DriverVerifyChangePasswordOtpSerializer,
)
from mobile_api.services.driver_profile_service import (
    driver_change_password,
    driver_request_change_password_otp,
    driver_verify_change_password_otp,
    get_driver_profile,
    update_driver_profile,
    update_driver_profile_photo,
)
from mobile_api.views.driver_auth import get_tenant_schema


def _mobile_jwt_payload(request) -> dict:
    """Token claims from DRF JWT auth (request.auth) or MobileUser.payload."""
    auth = getattr(request, 'auth', None)
    if isinstance(auth, dict):
        return auth
    user = getattr(request, 'user', None)
    payload = getattr(user, 'payload', None)
    return payload if isinstance(payload, dict) else {}


def _mobile_user_id(request) -> str:
    user = getattr(request, 'user', None)
    uid = getattr(user, 'user_id', None)
    return str(uid) if uid is not None else ''


def _mobile_tenant_schema(request) -> str:
    """Prefer JWT ``tenant_schema``; then ``MobileUser``; then header/middleware."""
    pl = _mobile_jwt_payload(request)
    ts = str(pl.get('tenant_schema') or '').strip()
    if ts:
        return ts
    user = getattr(request, 'user', None)
    schema = getattr(user, 'tenant_schema', None)
    if schema:
        return str(schema).strip()
    return get_tenant_schema(request)


class DriverRequestChangePasswordOtpView(MobileAPIView):
    """
    POST /api/v1/mobile/driver/auth/change-password/request-otp/

    Body: { "send_via": "email" | "mobile" }
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.auth_session'
    throttle_classes = [MobileOtpThrottle]

    def post(self, request):
        serializer = DriverRequestChangePasswordOtpSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        send_via = serializer.validated_data['send_via']
        result = driver_request_change_password_otp(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            send_via=send_via,
            jwt_payload=_mobile_jwt_payload(request),
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='profile_request_failed',
                message_key='mobile.error.generic',
                data={},
            )

        # Empty data: do not expose delivery pipeline status to clients.
        return self.success(
            message=_('mobile.auth.change_password_otp_sent'),
            data={},
            message_key='mobile.auth.change_password_otp_sent',
        )


class DriverVerifyChangePasswordOtpView(MobileAPIView):
    """
    POST /api/v1/mobile/driver/auth/change-password/verify-otp/

    Body: { "otp_code": "123456" }
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.auth_session'
    throttle_classes = [MobileOtpThrottle]

    def post(self, request):
        serializer = DriverVerifyChangePasswordOtpSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        otp_code = serializer.validated_data['otp_code']
        result = driver_verify_change_password_otp(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            otp_code=otp_code,
            jwt_payload=_mobile_jwt_payload(request),
        )

        if not result.get('success'):
            data = {
                'attempts_remaining': result.get('attempts_remaining', 0),
                'verified': result.get('verified', False),
            }
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='change_password_otp_verify_failed',
                message_key='mobile.validation.invalid_otp',
                data=data,
            )

        return self.success(
            message=_('mobile.auth.change_password_otp_verified'),
            data={
                'attempts_remaining': result.get('attempts_remaining', 0),
                'verified': result.get('verified', True),
            },
            message_key='mobile.auth.change_password_otp_verified',
        )


class DriverChangePasswordView(MobileAPIView):
    """
    POST /api/v1/mobile/driver/auth/change-password/

    Body:
      current_password, new_password, confirm_password, otp_code
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.auth_session'
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        serializer = DriverChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        payload = _mobile_jwt_payload(request)
        result = driver_change_password(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            current_password=serializer.validated_data['current_password'],
            new_password=serializer.validated_data['new_password'],
            otp_code=serializer.validated_data['otp_code'],
            jwt_payload=payload,
            access_jti=payload.get('jti'),
            access_exp_ts=payload.get('exp'),
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='change_password_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_('mobile.auth.password_changed_successfully'),
            data={},
            message_key='mobile.auth.password_changed_successfully',
        )


class DriverProfileView(MobileAPIView):
    """
    GET /api/v1/mobile/driver/profile/
    PUT /api/v1/mobile/driver/profile/
    PATCH /api/v1/mobile/driver/profile/  (same as PUT)

    PUT body (optional fields — send at least one):

      {
        "full_name": "...",
        "mobile_country_code": "966",
        "mobile_no": "...",
        "english_name": "...",
        "arabic_name": "...",
        "mobile_number": "...",
        "whatsapp_number": "...",
        "whatsapp_same_as_mobile": true
      }
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.profile'
    throttle_classes = [MobileUserThrottle]

    def get(self, request):
        result = get_driver_profile(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            jwt_payload=_mobile_jwt_payload(request),
            request=request,
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='profile_fetch_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_('mobile.profile.fetch_success'),
            data=result.get('profile') or {},
            message_key='mobile.profile.fetch_success',
        )

    def put(self, request):
        serializer = DriverProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        result = update_driver_profile(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            updates=dict(serializer.validated_data),
            jwt_payload=_mobile_jwt_payload(request),
            request=request,
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='profile_update_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_('mobile.profile.update_success'),
            data=result.get('profile') or {},
            message_key='mobile.profile.update_success',
        )

    def patch(self, request):
        """Alias for partial updates (same validation and body as ``PUT``)."""
        return self.put(request)


class DriverProfilePhotoUpdateView(MobileAPIView):
    """
    POST or PATCH /api/v1/mobile/driver/profile/photo/

    Multipart: profile_photo (image file)
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.profile'
    throttle_classes = [MobileUserThrottle]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        return self._update_photo(request)

    def patch(self, request):
        return self._update_photo(request)

    def _update_photo(self, request):
        serializer = DriverProfilePhotoUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        uploaded = serializer.validated_data['profile_photo']
        result = update_driver_profile_photo(
            user_id=_mobile_user_id(request),
            tenant_schema=_mobile_tenant_schema(request),
            uploaded_file=uploaded,
            jwt_payload=_mobile_jwt_payload(request),
            request=request,
        )

        if not result.get('success'):
            return self.error(
                message=result.get('error', _('mobile.validation.failed')),
                code='profile_photo_update_failed',
                message_key='mobile.error.generic',
                data={},
            )

        return self.success(
            message=_('mobile.profile.photo_updated'),
            data={
                'profile_photo_url': result.get('profile_photo_url'),
            },
            message_key='mobile.profile.photo_updated',
        )
