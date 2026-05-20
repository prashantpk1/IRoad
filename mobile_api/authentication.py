"""
mobile_api/authentication.py

DRF Custom Authentication class for Mobile API.

Flow:
  1. Extract Bearer token from Authorization header
  2. Verify JWT signature and expiry
  3. Return (user_representation, token_payload) on success
  4. Return None if no token (anonymous request)
  5. Raise AuthenticationFailed if token present but invalid

Usage:
  Configured globally in REST_FRAMEWORK settings.
  Individual views can override with authentication_classes = []
  to allow unauthenticated access (e.g. login endpoint).
"""
import jwt
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.utils.translation import gettext_lazy as _

from mobile_api.helpers.auth import (
    get_token_from_request,
    verify_token,
    TOKEN_TYPE_ACCESS,
)
from mobile_api.helpers.mobile_driver_session import load_mobile_driver_subject


class MobileUser:
    """
    Lightweight user representation for authenticated mobile requests.
    Not a Django model — just carries token claims.
    No database hit required.
    """
    def __init__(self, payload: dict):
        self.user_id = payload.get('user_id')
        self.tenant_schema = payload.get('tenant_schema')
        self.jti = payload.get('jti')
        self.payload = payload
        self.is_authenticated = True

    @property
    def pk(self):
        """DRF ``UserRateThrottle`` uses ``request.user.pk`` for cache keys."""
        return self.user_id

    def __str__(self):
        return f"MobileUser({self.user_id}@{self.tenant_schema})"


class MobileJWTAuthentication(BaseAuthentication):
    """
    Custom DRF authentication for Mobile API JWT tokens.

    Authenticates requests using:
      Authorization: Bearer <access_token>

    On every successful cryptographic verification, **re-loads** the tenant
    ``TenantUser`` and linked ``DriverMaster`` from the database so admin
    changes (inactive driver, deleted user, role edits, ``mobile_token_version``)
    take effect immediately on the next API call.

    Also enforces (when configured):
      - ``MOBILE_API_JWT_REQUIRE_TENANT_HINT`` — resolvable tenant context required
      - ``X-Tenant-ID`` / ``request.tenant`` consistency with JWT ``tenant_schema``
      - JWT claim binding to DB (email, ``driver_id``, ``role_name``) against tampering
      - Optional ``MOBILE_API_DRIVER_ROLE_ALLOWLIST`` CSV allow-list for ``role_name``

    Returns:
      (MobileUser instance, token_payload) on success
      None if no Authorization header (anonymous)

    Raises:
      AuthenticationFailed if token present but invalid/expired
    """

    def authenticate(self, request):
        token = get_token_from_request(request)

        # No token — anonymous request
        # Let permission class decide if this is allowed
        if token is None:
            return None

        # Token present — must be valid
        try:
            payload = verify_token(
                token,
                expected_type=TOKEN_TYPE_ACCESS,
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed(
                _('mobile.auth.token_expired')
            )
        except jwt.InvalidTokenError:
            raise AuthenticationFailed(
                _('mobile.auth.token_invalid')
            )

        if payload is None:
            raise AuthenticationFailed(
                _('mobile.auth.token_invalid')
            )

        # DB + tenant + claim binding (raises AuthenticationFailed)
        load_mobile_driver_subject(request, payload)

        # Build lightweight user object from token claims
        mobile_user = MobileUser(payload)
        return (mobile_user, payload)

    def authenticate_header(self, request):
        """
        Return string for WWW-Authenticate header on 401 responses.
        """
        return 'Bearer realm="Mobile API"'

