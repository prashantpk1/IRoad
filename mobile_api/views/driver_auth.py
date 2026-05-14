"""
mobile_api/views/driver_auth.py

Driver Authentication API Views.

Endpoints:
  POST /api/v1/mobile/driver/auth/login/
  POST /api/v1/mobile/driver/auth/forgot-password/
  POST /api/v1/mobile/driver/auth/verify-otp/
  POST /api/v1/mobile/driver/auth/reset-password/
  POST /api/v1/mobile/driver/auth/logout/
  POST /api/v1/mobile/driver/auth/delete-account/
"""
from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.views.base import MobileAPIView
from mobile_api.permissions import (
    AllowAnyMobile,
    IsMobileAuthenticated,
)
from mobile_api.throttling import (
    MobileAuthThrottle,
    MobileOtpThrottle,
)
from mobile_api.serializers.driver_auth import (
    DeleteAccountSerializer,
    DriverLoginSerializer,
    ForgotPasswordSerializer,
    VerifyOtpSerializer,
    ResetPasswordSerializer,
    LogoutSerializer,
)
from mobile_api.services.driver_auth_service import (
    driver_delete_account,
    driver_login,
    driver_forgot_password,
    driver_verify_otp,
    driver_reset_password,
    driver_logout,
)


def get_tenant_schema(request) -> str:
    """
    Get tenant schema from request.
    TenantMainMiddleware sets request.tenant automatically.
    Fallback to X-Tenant-ID header.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant and getattr(tenant, 'schema_name', None):
        return tenant.schema_name

    tenant_identifier = (request.headers.get('X-Tenant-ID') or '').strip()
    if not tenant_identifier:
        return ''

    # Fallback resolution: header may be tenant UUID or schema name.
    try:
        from iroad_tenants.models import TenantRegistry
        tenant_registry = TenantRegistry.objects.filter(
            tenant_profile_id=tenant_identifier
        ).first()
        if tenant_registry:
            return tenant_registry.schema_name
        tenant_registry = TenantRegistry.objects.filter(
            schema_name=tenant_identifier
        ).first()
        if tenant_registry:
            return tenant_registry.schema_name
    except Exception:
        pass

    return ''


class DriverLoginView(MobileAPIView):
    """
    API 1: Driver Login
    POST /api/v1/mobile/driver/auth/login/

    Request body:
      { "email": "...", "password": "..." }

    Response success:
      {
        "status": 1,
        "message": "Login successful",
        "data": {
          "access_token": "...",
          "refresh_token": "...",
          "driver": { ... }
        }
      }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        serializer = DriverLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(
                message=_('mobile.validation.failed'),
                data={'errors': serializer.errors},
            )

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        tenant_schema = get_tenant_schema(request)

        result = driver_login(
            email=email,
            password=password,
            tenant_schema=tenant_schema,
            request=request,
        )

        if not result['success']:
            return self.error(
                message=result['error'],
                http_code=401,
            )

        return self.success(
            message=_('mobile.auth.login_success'),
            data={
                'access_token': result['tokens']['access_token'],
                'refresh_token': result['tokens']['refresh_token'],
                'driver': result['driver'],
            },
        )


class DriverForgotPasswordView(MobileAPIView):
    """
    API 2: Forgot Password
    POST /api/v1/mobile/driver/auth/forgot-password/

    Request body:
      { "email": "..." }

    Response: Always success (prevents email enumeration)
      {
        "status": 1,
        "message": "OTP sent if email is registered",
        "data": {}
      }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileOtpThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(
                message=_('mobile.validation.failed'),
                data={'errors': serializer.errors},
            )

        email = serializer.validated_data['email']
        tenant_schema = get_tenant_schema(request)

        result = driver_forgot_password(
            email=email,
            tenant_schema=tenant_schema,
        )

        if not result['success']:
            return self.error(
                message=result['error'],
                data={},
            )
        return self.success(
            message=_('mobile.auth.otp_sent'),
            data={},
        )


class DriverVerifyOtpView(MobileAPIView):
    """
    API 3: Verify OTP
    POST /api/v1/mobile/driver/auth/verify-otp/

    Request body:
      { "email": "...", "otp_code": "123456" }

    Response success:
      { "status": 1, "message": "OTP verified", "data": {} }

    Response failure:
      { "status": 0, "message": "...", "data": {} }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileOtpThrottle]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(
                message=_('mobile.validation.failed'),
                data={'errors': serializer.errors},
            )

        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp_code']
        tenant_schema = get_tenant_schema(request)

        result = driver_verify_otp(
            email=email,
            otp_code=otp_code,
            tenant_schema=tenant_schema,
        )

        if not result['success']:
            data = {}
            if 'attempts_remaining' in result:
                data['attempts_remaining'] = (
                    result['attempts_remaining']
                )
            return self.error(
                message=result['error'],
                data=data,
            )

        return self.success(
            message=_('mobile.auth.otp_verified'),
        )


class DriverResetPasswordView(MobileAPIView):
    """
    API 4: Reset Password
    POST /api/v1/mobile/driver/auth/reset-password/

    Request body:
      {
        "email": "...",
        "otp_code": "123456",
        "new_password": "...",
        "confirm_password": "..."
      }

    Response success:
      { "status": 1, "message": "Password reset successful", "data": {} }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(
                message=_('mobile.validation.failed'),
                data={'errors': serializer.errors},
            )

        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp_code']
        new_password = serializer.validated_data['new_password']
        tenant_schema = get_tenant_schema(request)

        result = driver_reset_password(
            email=email,
            otp_code=otp_code,
            new_password=new_password,
            tenant_schema=tenant_schema,
        )

        if not result['success']:
            return self.error(
                message=result['error'],
            )

        return self.success(
            message=_('mobile.auth.password_reset_success'),
        )


class DriverLogoutView(MobileAPIView):
    """
    API 5: Logout
    POST /api/v1/mobile/driver/auth/logout/

    Headers:
      Authorization: Bearer <access_token>

    No request body needed.

    Response:
      { "status": 1, "message": "Logged out successfully", "data": {} }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        from mobile_api.helpers.auth import (
            get_token_from_request,
            verify_token,
            TOKEN_TYPE_ACCESS,
        )

        token = get_token_from_request(request)
        if not token:
            return self.error(
                message=_('mobile.auth.token_invalid'),
                http_code=401,
            )

        payload = verify_token(
            token,
            expected_type=TOKEN_TYPE_ACCESS,
        )
        if not payload:
            return self.error(
                message=_('mobile.auth.token_invalid'),
                http_code=401,
            )

        tenant_schema = get_tenant_schema(request) or payload.get('tenant_schema', '')
        driver_logout(
            user_id=payload.get('user_id', ''),
            jti=payload.get('jti', ''),
            tenant_schema=tenant_schema,
            exp_ts=payload.get('exp'),
        )

        return self.success(
            message=_('mobile.auth.logout_success'),
        )


class DriverDeleteAccountView(MobileAPIView):
    """
    API 6: Delete account (soft-delete TenantUser)
    POST /api/v1/mobile/driver/auth/delete-account/

    Authenticated (default ``MobileJWTAuthentication``). Body:
      { "password": "..." }

    Missing/invalid JWT or deleted subject: handled by DRF auth / exception
    handler (status 2). Wrong password / already deleted: service + this view.
    Inactive ``TenantUser`` cannot obtain a driver JWT via login; if status
    changes mid-session, ``driver_delete_account`` still enforces password + soft-delete.

    Response success:
      { "status": 1, "message": "<account_deleted_success>", "data": {} }
    """

    permission_classes = [IsMobileAuthenticated]
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        if not serializer.is_valid():
            return self.error(
                message=_('mobile.validation.failed'),
                data={'errors': serializer.errors},
            )

        mobile_user = getattr(request, 'user', None)
        user_id = getattr(mobile_user, 'user_id', None)
        if not user_id:
            return self.auth_error(_('mobile.auth.unauthorized'))

        tenant_schema = (
            get_tenant_schema(request)
            or getattr(mobile_user, 'tenant_schema', '')
            or ''
        ).strip()
        if not tenant_schema:
            return self.auth_error(_('mobile.auth.unauthorized'))

        from tenant_workspace.models import TenantUser

        with schema_context(tenant_schema):
            tenant_user = TenantUser.all_objects.filter(pk=user_id).first()

        if tenant_user is None:
            return self.auth_error(_('mobile.auth.unauthorized'))

        if getattr(tenant_user, 'is_deleted', False):
            return self.error(
                message=_('mobile.auth.account_already_deleted'),
                http_code=401,
            )

        password = serializer.validated_data['password']
        result = driver_delete_account(request, tenant_user, password)

        if not result.get('success'):
            err = result.get('error', _('mobile.validation.failed'))
            if err == _('mobile.auth.invalid_credentials'):
                return self.error(message=err, http_code=401)
            if err == _('mobile.auth.account_already_deleted'):
                return self.error(message=err, http_code=400)
            return self.error(message=err, http_code=401)

        return self.success(
            message=str(result.get('message', '')),
            data={},
        )
