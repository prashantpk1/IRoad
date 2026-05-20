"""
mobile_api/views/driver_auth.py

Driver Authentication API Views.

Endpoints:
  POST /api/v1/mobile/driver/auth/login/
  POST /api/v1/mobile/driver/auth/refresh/
  POST /api/v1/mobile/driver/auth/forgot-password/
  POST /api/v1/mobile/driver/auth/verify-otp/
  POST /api/v1/mobile/driver/auth/reset-password/
  POST /api/v1/mobile/driver/auth/logout/
  POST /api/v1/mobile/driver/auth/logout-all/
  POST /api/v1/mobile/driver/auth/delete-account/

Tenant safety:
  Login resolves the subscriber from **email + password** (optional JSON
  ``tenant_id`` only when you must disambiguate). ``X-Tenant-ID`` is **not**
  used for login tenant selection.

  Authenticated routes merge optional ``tenant_id`` / ``X-Tenant-ID`` /
  ``request.tenant`` with the JWT ``tenant_schema`` (see
  ``merge_mobile_jwt_tenant_context``) so clients can rely on the Bearer token
  alone unless they choose to send an explicit tenant hint.
"""
from django.conf import settings
from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.helpers.mobile_tenant import (
    get_mobile_tenant_schema_from_request,
    merge_mobile_jwt_tenant_context,
    resolve_active_tenant_registry,
    resolve_mobile_auth_tenant_context,
)

from mobile_api.views.base import MobileAPIView
from mobile_api.permissions import (
    AllowAnyMobile,
    HasViewMobileCapability,
    IsDriver,
    IsMobileAuthenticated,
)
from mobile_api.throttling import (
    MobileAuthThrottle,
    MobileForgotPasswordThrottle,
    MobileLoginThrottle,
    MobileResetPasswordThrottle,
    MobileVerifyOtpThrottle,
)
from mobile_api.serializers.driver_auth import (
    DeleteAccountSerializer,
    DriverLoginSerializer,
    DriverRefreshSerializer,
    ForgotPasswordSerializer,
    VerifyOtpSerializer,
    ResetPasswordSerializer,
    LogoutSerializer,
)
from mobile_api.services.driver_auth_service import (
    driver_delete_account,
    driver_login,
    driver_refresh_session,
    driver_forgot_password,
    driver_verify_otp,
    driver_reset_password,
    driver_logout,
    driver_logout_all_devices,
)
from mobile_api.response_envelope import mobile_auth_error_message_key


def get_tenant_schema(request) -> str:
    """
    Best-effort tenant ``schema_name`` from ``request.tenant`` / ``X-Tenant-ID``.

    For **authenticated** mobile driver views, prefer ``request.auth`` /
    ``MobileUser.tenant_schema`` (JWT) in ``driver_profile._mobile_tenant_schema``
    instead of relying on this helper alone.
    """
    return get_mobile_tenant_schema_from_request(request)


def _tenant_context_error_response(view, err: str):
    if err == 'invalid_tenant':
        return view.error(
            message=_('mobile.auth.invalid_tenant'),
            http_code=400,
            code='invalid_tenant',
            message_key='mobile.auth.invalid_tenant',
        )
    if err == 'tenant_mismatch':
        return view.error(
            message=_('mobile.auth.tenant_mismatch'),
            http_code=403,
            code='tenant_mismatch',
            message_key='mobile.auth.tenant_mismatch',
        )
    return None


def _require_explicit_auth_tenant_hint(view, schema: str):
    """
    Enforce subscriber context on unauthenticated password-reset endpoints.

    Controlled by ``MOBILE_API_AUTH_ENDPOINTS_REQUIRE_TENANT_HINT`` (default True).
    """
    if getattr(settings, 'MOBILE_API_AUTH_ENDPOINTS_REQUIRE_TENANT_HINT', True):
        if not (schema or '').strip():
            return view.error(
                message=_('mobile.auth.tenant_required'),
                http_code=400,
                code='tenant_required',
                message_key='mobile.auth.tenant_required',
            )
    return None


class DriverLoginView(MobileAPIView):
    """
    API 1: Driver Login
    POST /api/v1/mobile/driver/auth/login/

    Request body:
      { "email": "...", "password": "...", "device_platform": "iOS"|"Android", "device_id": "<FCM token>", "device_name": "..." }

    Optional: ``tenant_id`` (subscriber UUID or ``schema_name``) only when the
    same email/password exists on more than one tenant. Tenant is otherwise
    resolved from credentials only (``X-Tenant-ID`` is ignored for login).

    Optional device fields (mobile apps):
      ``device_id`` — FCM registration token (long string).
      ``device_platform`` — e.g. ``iOS`` or ``Android``.
      ``device_name`` — marketing name, e.g. ``iPhone 16``, ``Samsung Galaxy S24``.

    Response success (non-exhaustive):
      {
        "status": 1,
        "message": "Login successful",
        "data": {
          "access_token": "...",
          "refresh_token": "...",
          "token_type": "Bearer",
          "expires_in": 3600,
          "refresh_expires_in": 2592000,
          "driver": { ... },
          "organization": { "tenant_id", "schema_name", "company_name" },
          "assigned_truck": { ... } | null,
          "permissions": { ... },
          "profile": { ... }
        }
      }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileLoginThrottle]

    def post(self, request):
        serializer = DriverLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        body_tenant = (serializer.validated_data.get('tenant_id') or '').strip()
        tenant_schema = ''
        if body_tenant:
            reg = resolve_active_tenant_registry(body_tenant)
            if reg is None:
                return self.error(
                    message=_('mobile.auth.invalid_tenant'),
                    http_code=400,
                    code='invalid_tenant',
                    message_key='mobile.auth.invalid_tenant',
                )
            tenant_schema = str(reg.schema_name).strip()
        device = {
            'device_id': (serializer.validated_data.get('device_id') or '').strip(),
            'platform': (serializer.validated_data.get('device_platform') or '').strip(),
            'name': (serializer.validated_data.get('device_name') or '').strip(),
        }

        result = driver_login(
            email=email,
            password=password,
            tenant_schema=tenant_schema,
            request=request,
            device=device,
        )

        if not result['success']:
            code = result.get('error_code', 'auth_failed')
            http_code = 401
            if code == 'tenant_ambiguous':
                http_code = 409
            elif code == 'invalid_tenant':
                http_code = 400
            elif code == 'tenant_required':
                http_code = 400
            elif code == 'server_error':
                http_code = 500
            return self.error(
                message=result['error'],
                code=code,
                message_key=mobile_auth_error_message_key(code),
                details=(
                    {'candidates': result.get('candidates') or []}
                    if code == 'tenant_ambiguous'
                    else {}
                ),
                http_code=http_code,
            )

        return self.success(
            message=_('mobile.auth.login_success'),
            data=result['data'],
            message_key='mobile.auth.login_success',
        )


class DriverRefreshTokenView(MobileAPIView):
    """
    API 1b: Rotate refresh token (session continuation without password).

    POST /api/v1/mobile/driver/auth/refresh/

    Request (preferred):
      { "refresh_token": "<JWT refresh>", "tenant_id": "<uuid or schema_name>" }

    Fallback when ``refresh_token`` is empty:
      Authorization: Bearer <JWT refresh>

    ``tenant_id`` (or ``X-Tenant-ID``) must match the refresh token's
    ``tenant_schema`` when provided; if omitted, the token's schema is used.

    Success ``data``:
      access_token, refresh_token, token_type, expires_in, refresh_expires_in

    Security (summary):
      - ``verify_token`` (signature, expiry, iss/aud, blacklist)
      - Redis SET NX per refresh ``jti`` (one-time use / replay & race)
      - Blacklist consumed refresh ``jti`` then mint new pair (same ``rt_fam``)
      - Optional ``X-Tenant-ID`` must match token ``tenant_schema`` when sent

    Lifecycle (text):

        Login → (access, refresh_v1)
        Refresh(refresh_v1) → consume v1, blacklist v1 → (access', refresh_v2)
        Replay(refresh_v1) → consume fails or blacklist → 401 ``refresh_replay``
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        from mobile_api.helpers.auth import get_token_from_request

        serializer = DriverRefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        refresh = (serializer.validated_data.get('refresh_token') or '').strip()
        if not refresh:
            refresh = (get_token_from_request(request) or '').strip()
        if not refresh:
            return self.auth_error(
                _('mobile.auth.refresh_invalid'),
                code='refresh_invalid',
                message_key='mobile.auth.refresh_invalid',
            )

        body_tid = (serializer.validated_data.get('tenant_id') or '').strip()
        tenant_hint, terr = resolve_mobile_auth_tenant_context(
            request,
            body_tenant_id=body_tid,
        )
        terr_resp = _tenant_context_error_response(self, terr or '')
        if terr_resp is not None:
            return terr_resp
        result = driver_refresh_session(
            refresh,
            request=request,
            expected_tenant_schema=tenant_hint,
        )

        if not result['success']:
            code = result.get('error_code', 'refresh_invalid')
            http = 401
            if code == 'tenant_mismatch':
                http = 403
            if code == 'invalid_tenant':
                http = 400
            if code == 'tenant_required':
                http = 400
            return self.error(
                message=result['error'],
                code=code,
                message_key=mobile_auth_error_message_key(code),
                http_code=http,
            )

        return self.success(
            message=_('mobile.auth.refresh_success'),
            data=result['data'],
            message_key='mobile.auth.refresh_success',
        )


class DriverForgotPasswordView(MobileAPIView):
    """
    API 2: Forgot Password
    POST /api/v1/mobile/driver/auth/forgot-password/

    Request body:
      { "email": "..." }

    Response: Same success envelope whether or not an email was sent
      (anti-enumeration). ``email_dispatch_status`` is for internal use only
      and is not exposed in the HTTP response by default.

      {
        "status": 1,
        "message": "<forgot_password_accepted>",
        "data": {}
      }
    """
    authentication_classes = []
    permission_classes = [AllowAnyMobile]
    throttle_classes = [MobileForgotPasswordThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        email = serializer.validated_data['email']
        body_tid = (serializer.validated_data.get('tenant_id') or '').strip()
        tenant_schema, terr = resolve_mobile_auth_tenant_context(
            request,
            body_tenant_id=body_tid,
        )
        terr_resp = _tenant_context_error_response(self, terr or '')
        if terr_resp is not None:
            return terr_resp
        req_resp = _require_explicit_auth_tenant_hint(self, tenant_schema)
        if req_resp is not None:
            return req_resp

        result = driver_forgot_password(
            email=email,
            tenant_schema=tenant_schema,
            request=request,
        )

        if not result['success']:
            code = result.get('error_code', '') or 'error'
            http = 409 if code == 'tenant_ambiguous_operation' else 400
            return self.error(
                message=result['error'],
                code=code,
                message_key=mobile_auth_error_message_key(code),
                http_code=http,
            )
        return self.success(
            message=_('mobile.auth.forgot_password_accepted'),
            data={},
            message_key='mobile.auth.forgot_password_accepted',
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
    throttle_classes = [MobileVerifyOtpThrottle]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp_code']
        body_tid = (serializer.validated_data.get('tenant_id') or '').strip()
        tenant_schema, terr = resolve_mobile_auth_tenant_context(
            request,
            body_tenant_id=body_tid,
        )
        terr_resp = _tenant_context_error_response(self, terr or '')
        if terr_resp is not None:
            return terr_resp
        req_resp = _require_explicit_auth_tenant_hint(self, tenant_schema)
        if req_resp is not None:
            return req_resp

        result = driver_verify_otp(
            email=email,
            otp_code=otp_code,
            tenant_schema=tenant_schema,
            request=request,
        )

        if not result['success']:
            code = result.get('error_code', '') or 'error'
            return self.error(
                message=result['error'],
                code=code,
                message_key=mobile_auth_error_message_key(code),
                http_code=409 if code == 'tenant_ambiguous_operation' else 400,
            )

        return self.success(
            message=_('mobile.auth.otp_verified'),
            data={},
            message_key='mobile.auth.otp_verified',
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
    throttle_classes = [MobileResetPasswordThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp_code']
        new_password = serializer.validated_data['new_password']
        body_tid = (serializer.validated_data.get('tenant_id') or '').strip()
        tenant_schema, terr = resolve_mobile_auth_tenant_context(
            request,
            body_tenant_id=body_tid,
        )
        terr_resp = _tenant_context_error_response(self, terr or '')
        if terr_resp is not None:
            return terr_resp
        req_resp = _require_explicit_auth_tenant_hint(self, tenant_schema)
        if req_resp is not None:
            return req_resp

        result = driver_reset_password(
            email=email,
            otp_code=otp_code,
            new_password=new_password,
            tenant_schema=tenant_schema,
            request=request,
        )

        if not result['success']:
            code = result.get('error_code', '') or 'error'
            return self.error(
                message=result['error'],
                code=code,
                message_key=mobile_auth_error_message_key(code),
                http_code=409 if code == 'tenant_ambiguous_operation' else 400,
            )

        return self.success(
            message=_('mobile.auth.password_reset_success'),
            data={},
            message_key='mobile.auth.password_reset_success',
        )


class DriverLogoutView(MobileAPIView):
    """
    API 5: Logout
    POST /api/v1/mobile/driver/auth/logout/

    Headers:
      Authorization: Bearer <access_token>

    Optional body (recommended — full session teardown):
      { "refresh_token": "<JWT refresh>" }

    Session invalidation:
      - Access JTI blacklisted; optional refresh JTI blacklisted when sent.
      - All JWTs sharing the same ``rt_fam`` as the access (and refresh) claims
        are rejected via Redis family invalidation (defense in depth).

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
            return self.auth_error(
                _('mobile.auth.token_invalid'),
                code='token_invalid',
                message_key='mobile.auth.token_invalid',
            )

        payload = verify_token(
            token,
            expected_type=TOKEN_TYPE_ACCESS,
        )
        if not payload:
            return self.auth_error(
                _('mobile.auth.token_invalid'),
                code='token_invalid',
                message_key='mobile.auth.token_invalid',
            )

        serializer = LogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)
        refresh_body = (serializer.validated_data.get('refresh_token') or '').strip()

        tenant_schema, merr = merge_mobile_jwt_tenant_context(request, payload)
        if merr == 'invalid_tenant':
            return _tenant_context_error_response(self, merr)
        if merr == 'tenant_mismatch':
            return _tenant_context_error_response(self, merr)
        if getattr(settings, 'MOBILE_API_JWT_REQUIRE_TENANT_HINT', True):
            if not (tenant_schema or '').strip():
                return self.auth_error(
                    _('mobile.auth.tenant_required'),
                    code='tenant_required',
                    message_key='mobile.auth.tenant_required',
                )

        driver_logout(
            user_id=payload.get('user_id', ''),
            jti=payload.get('jti', ''),
            tenant_schema=tenant_schema,
            exp_ts=payload.get('exp'),
            refresh_token=refresh_body or None,
            access_rt_fam=(payload.get('rt_fam') or None),
            request=request,
        )

        return self.success(
            message=_('mobile.auth.logout_success'),
            data={},
            message_key='mobile.auth.logout_success',
        )


def _mobile_jwt_payload_from_request(request) -> dict:
    """Claims dict from DRF JWT auth (``request.auth``) or ``MobileUser.payload``."""
    auth = getattr(request, 'auth', None)
    if isinstance(auth, dict):
        return auth
    user = getattr(request, 'user', None)
    pl = getattr(user, 'payload', None)
    return pl if isinstance(pl, dict) else {}


class DriverLogoutAllDevicesView(MobileAPIView):
    """
    API 5b: Logout from **all** devices (global session kill).

    POST /api/v1/mobile/driver/auth/logout-all/

    Authenticated: ``Authorization: Bearer <access_token>``.

    Optional body (recommended):
      { "refresh_token": "<current refresh JWT>" }

    Effects:
      - Blacklists current access (and refresh when provided) JTIs.
      - Invalidates refresh **families** for those tokens in Redis.
      - Increments ``TenantUser.mobile_token_version`` so every outstanding JWT
        fails auth until the user signs in again (same mechanism as password change).

    Response:
      { "status": 1, "message": "<logout_all_success>", "data": {} }
    """

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.auth_session'
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        payload = _mobile_jwt_payload_from_request(request)
        user_id = str(payload.get('user_id') or '').strip()
        if not user_id:
            return self.auth_error(
                _('mobile.auth.unauthorized'),
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        tenant_schema, merr = merge_mobile_jwt_tenant_context(request, payload)
        if merr == 'invalid_tenant':
            return _tenant_context_error_response(self, merr)
        if merr == 'tenant_mismatch':
            return _tenant_context_error_response(self, merr)
        if getattr(settings, 'MOBILE_API_JWT_REQUIRE_TENANT_HINT', True):
            if not (tenant_schema or '').strip():
                return self.auth_error(
                    _('mobile.auth.tenant_required'),
                    code='tenant_required',
                    message_key='mobile.auth.tenant_required',
                )
        if not tenant_schema:
            return self.auth_error(
                _('mobile.auth.unauthorized'),
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        serializer = LogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)
        refresh_body = (serializer.validated_data.get('refresh_token') or '').strip()

        result = driver_logout_all_devices(
            user_id=user_id,
            tenant_schema=tenant_schema,
            access_jti=str(payload.get('jti') or ''),
            access_exp_ts=payload.get('exp'),
            access_rt_fam=(payload.get('rt_fam') or None),
            refresh_token=refresh_body or None,
            request=request,
        )

        if not result.get('success'):
            return self.auth_error(
                result.get('error', _('mobile.auth.unauthorized')),
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        return self.success(
            message=_('mobile.auth.logout_all_success'),
            data=result.get('data') or {},
            message_key='mobile.auth.logout_all_success',
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

    permission_classes = [
        IsMobileAuthenticated,
        IsDriver,
        HasViewMobileCapability,
    ]
    required_mobile_capability = 'mobile.driver.auth_session'
    throttle_classes = [MobileAuthThrottle]

    def post(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        if not serializer.is_valid():
            return self.validation_error(serializer)

        mobile_user = getattr(request, 'user', None)
        user_id = getattr(mobile_user, 'user_id', None)
        if not user_id:
            return self.auth_error(
                _('mobile.auth.unauthorized'),
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        payload = getattr(mobile_user, 'payload', None) or {}
        tenant_schema, merr = merge_mobile_jwt_tenant_context(request, payload)
        if merr == 'invalid_tenant':
            return _tenant_context_error_response(self, merr)
        if merr == 'tenant_mismatch':
            return _tenant_context_error_response(self, merr)
        if getattr(settings, 'MOBILE_API_JWT_REQUIRE_TENANT_HINT', True):
            if not (tenant_schema or '').strip():
                return self.auth_error(
                    _('mobile.auth.tenant_required'),
                    code='tenant_required',
                    message_key='mobile.auth.tenant_required',
                )
        if not tenant_schema:
            return self.auth_error(
                _('mobile.auth.unauthorized'),
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        from tenant_workspace.models import TenantUser

        with schema_context(tenant_schema):
            tenant_user = TenantUser.all_objects.filter(pk=user_id).first()

        if tenant_user is None:
            return self.auth_error(
                _('mobile.auth.unauthorized'),
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        if getattr(tenant_user, 'is_deleted', False):
            return self.error(
                message=_('mobile.auth.account_already_deleted'),
                http_code=401,
                code='account_already_deleted',
                message_key='mobile.auth.account_already_deleted',
            )

        password = serializer.validated_data['password']
        result = driver_delete_account(request, tenant_user, password)

        if not result.get('success'):
            err = result.get('error', _('mobile.validation.failed'))
            if err == _('mobile.auth.invalid_credentials'):
                return self.error(
                    message=err,
                    http_code=401,
                    code='invalid_credentials',
                    message_key='mobile.auth.invalid_credentials',
                )
            if err == _('mobile.auth.account_already_deleted'):
                return self.error(
                    message=err,
                    http_code=400,
                    code='account_already_deleted',
                    message_key='mobile.auth.account_already_deleted',
                )
            return self.error(
                message=err,
                http_code=401,
                code='unauthorized',
                message_key='mobile.auth.unauthorized',
            )

        return self.success(
            message=str(result.get('message', '')),
            data={},
            message_key='mobile.auth.account_deleted_success',
        )
