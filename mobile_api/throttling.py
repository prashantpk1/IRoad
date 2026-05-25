"""
mobile_api/throttling.py

Custom throttle classes for Mobile API rate limiting.

Throttle rates configured in REST_FRAMEWORK settings:
  'mobile_auth': '12/minute'       — refresh, logout, etc.
  'mobile_login': '6/minute'      — password login only
  'mobile_otp': '5/minute'          — generic OTP-style endpoints (e.g. profile)
  'mobile_forgot_password': '5/minute'
  'mobile_verify_otp': '15/minute'
  'mobile_reset_password': '8/minute'
  'anon': '30/minute'               — unauthenticated general
  'user': '100/minute'              — authenticated general

Usage in views:
  class LoginView(APIView):
      throttle_classes = [MobileAuthThrottle]

  class OtpView(APIView):
      throttle_classes = [MobileOtpThrottle]
"""
from rest_framework.throttling import (
    AnonRateThrottle,
    UserRateThrottle,
)


class MobileLoginThrottle(AnonRateThrottle):
    """Driver password login only (stricter than refresh/logout)."""
    scope = 'mobile_login'


class MobileAuthThrottle(AnonRateThrottle):
    """
    Throttle for mobile auth endpoints other than password login
    (refresh, logout, etc.). Login uses ``MobileLoginThrottle``.
    Rate: see REST_FRAMEWORK ``DEFAULT_THROTTLE_RATES`` ``mobile_auth``.
    """
    scope = 'mobile_auth'


class MobileOtpThrottle(AnonRateThrottle):
    """
    Strictest throttle for OTP endpoints.
    Request OTP, verify OTP.
    Rate: 5 requests/minute per IP.
    """
    scope = 'mobile_otp'


class MobileForgotPasswordThrottle(AnonRateThrottle):
    """Driver forgot-password: issue / no-op path (per-IP burst control)."""
    scope = 'mobile_forgot_password'


class MobileVerifyOtpThrottle(AnonRateThrottle):
    """Driver verify-OTP (per-IP; pairs with cache-backed verify limits)."""
    scope = 'mobile_verify_otp'


class MobileResetPasswordThrottle(AnonRateThrottle):
    """Driver reset-password after OTP verify."""
    scope = 'mobile_reset_password'


class MobileUserThrottle(UserRateThrottle):
    """
    Standard throttle for authenticated endpoints.
    Rate: 100 requests/minute per user.
    """
    scope = 'user'


class MobileJobListThrottle(UserRateThrottle):
    """
    Driver job list feeds (shipments, movements, summary).

    Stricter than generic ``user`` throttle to protect DB on large tenants.
    Rate: see REST_FRAMEWORK ``mobile_jobs``.
    """
    scope = 'mobile_jobs'


class MobileAnonThrottle(AnonRateThrottle):
    """
    Standard throttle for unauthenticated endpoints.
    Rate: 30 requests/minute per IP.
    """
    scope = 'anon'

