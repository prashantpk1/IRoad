"""
mobile_api/helpers/password_reset_security.py

Enterprise controls for mobile **forgot-password / verify OTP / reset** flows:

- Cache-backed rate limits (per email+tenant, per IP) with safe fallbacks
- Constant-time OTP string comparison
- Timing jitter to reduce cross-request signal for enumeration
- Structured audit breadcrumbs (no raw OTP, minimal email surface)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

from django.conf import settings

logger = logging.getLogger('mobile_api')


def email_fingerprint(email: str) -> str:
    """Stable non-reversible identifier for logs and cache keys (not PII)."""
    normalized = (email or '').strip().lower().encode('utf-8', errors='ignore')
    return hashlib.sha256(normalized).hexdigest()[:20]


def client_ip_from_request(request: Any) -> str:
    if request is None:
        return ''
    try:
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return (xff.split(',')[0] or '').strip()[:45]
        return (request.META.get('REMOTE_ADDR') or '').strip()[:45]
    except Exception:
        return ''


def _rate_window_seconds() -> int:
    return int(
        getattr(settings, 'MOBILE_API_PASSWORD_RESET_RATE_WINDOW_SECONDS', 3600)
        or 3600,
    )


def _cache_incr(key: str, timeout: int) -> int:
    """Increment a counter in cache; returns new value (best-effort)."""
    try:
        from django.core.cache import cache

        raw = cache.get(key)
        n = int(raw) + 1 if raw is not None else 1
        cache.set(key, n, timeout=timeout)
        return n
    except Exception as exc:
        logger.warning('password_reset cache incr failed key=%s: %s', key[:48], exc)
        return 0


def forgot_password_rate_allow(
    *,
    email: str,
    tenant_schema: str,
    request: Any,
) -> bool:
    """
    False when forgot-password **sends** should be suppressed (rate limited).

    Fail-open on cache errors so legitimate users are not locked out if Redis
    is misconfigured; failures are logged.
    """
    try:
        from django.core.cache import cache

        window = _rate_window_seconds()
        fp = email_fingerprint(email)
        ip = client_ip_from_request(request) or 'unknown'
        max_per_email = int(
            getattr(settings, 'MOBILE_API_PASSWORD_RESET_FORGOT_EMAIL_MAX_PER_HOUR', 5)
            or 5,
        )
        max_per_ip = int(
            getattr(settings, 'MOBILE_API_PASSWORD_RESET_FORGOT_IP_MAX_PER_HOUR', 25)
            or 25,
        )
        e_key = f'm_pwreset:forgot:em:{tenant_schema}:{fp}'
        i_key = f'm_pwreset:forgot:ip:{ip}'
        ec = int(cache.get(e_key, 0) or 0)
        ic = int(cache.get(i_key, 0) or 0)
        if ec >= max_per_email or ic >= max_per_ip:
            return False
    except Exception as exc:
        logger.warning('password_reset forgot rate read failed: %s', exc)
        return not bool(
            getattr(
                settings,
                'MOBILE_API_PASSWORD_RESET_RATE_FAIL_CLOSED_ON_CACHE_ERROR',
                False,
            )
        )
    return True


def forgot_password_rate_record_send(
    *,
    email: str,
    tenant_schema: str,
    request: Any,
) -> None:
    """Record a successful OTP **issue** for rate limiting."""
    window = _rate_window_seconds()
    fp = email_fingerprint(email)
    ip = client_ip_from_request(request) or 'unknown'
    _cache_incr(f'm_pwreset:forgot:em:{tenant_schema}:{fp}', window)
    _cache_incr(f'm_pwreset:forgot:ip:{ip}', window)


def verify_otp_rate_allow(
    *,
    email: str,
    tenant_schema: str,
    request: Any,
) -> bool:
    """Throttle OTP verify attempts per IP (and per email fingerprint)."""
    try:
        from django.core.cache import cache

        window = _rate_window_seconds()
        fp = email_fingerprint(email)
        ip = client_ip_from_request(request) or 'unknown'
        max_verify_ip = int(
            getattr(settings, 'MOBILE_API_PASSWORD_RESET_VERIFY_IP_MAX_PER_HOUR', 60)
            or 60,
        )
        max_verify_em = int(
            getattr(settings, 'MOBILE_API_PASSWORD_RESET_VERIFY_EMAIL_MAX_PER_HOUR', 40)
            or 40,
        )
        i_key = f'm_pwreset:verify:ip:{ip}'
        e_key = f'm_pwreset:verify:em:{tenant_schema}:{fp}'
        if int(cache.get(i_key, 0) or 0) >= max_verify_ip:
            return False
        if int(cache.get(e_key, 0) or 0) >= max_verify_em:
            return False
    except Exception as exc:
        logger.warning('password_reset verify rate read failed: %s', exc)
        return not bool(
            getattr(
                settings,
                'MOBILE_API_PASSWORD_RESET_RATE_FAIL_CLOSED_ON_CACHE_ERROR',
                False,
            )
        )
    return True


def verify_otp_rate_record_attempt(
    *,
    email: str,
    tenant_schema: str,
    request: Any,
) -> None:
    """Count a verify attempt (success or failure) against brute-force budgets."""
    window = _rate_window_seconds()
    fp = email_fingerprint(email)
    ip = client_ip_from_request(request) or 'unknown'
    _cache_incr(f'm_pwreset:verify:ip:{ip}', window)
    _cache_incr(f'm_pwreset:verify:em:{tenant_schema}:{fp}', window)


def reset_password_rate_allow(*, request: Any) -> bool:
    """Throttle reset-password submissions per IP."""
    try:
        from django.core.cache import cache

        window = _rate_window_seconds()
        ip = client_ip_from_request(request) or 'unknown'
        max_r = int(
            getattr(settings, 'MOBILE_API_PASSWORD_RESET_RESET_IP_MAX_PER_HOUR', 20)
            or 20,
        )
        if int(cache.get(f'm_pwreset:reset:ip:{ip}', 0) or 0) >= max_r:
            return False
    except Exception as exc:
        logger.warning('password_reset reset rate read failed: %s', exc)
        return not bool(
            getattr(
                settings,
                'MOBILE_API_PASSWORD_RESET_RATE_FAIL_CLOSED_ON_CACHE_ERROR',
                False,
            )
        )
    return True


def reset_password_rate_record(*, request: Any) -> None:
    window = _rate_window_seconds()
    ip = client_ip_from_request(request) or 'unknown'
    _cache_incr(f'm_pwreset:reset:ip:{ip}', window)


def otp_compare_constant_time(stored_code: str, provided_code: str) -> bool:
    """Constant-time comparison for OTP digit strings."""
    a = (stored_code or '').strip().encode('utf-8')
    b = (provided_code or '').strip().encode('utf-8')
    if len(a) != 6 or len(b) != 6:
        return False
    return hmac.compare_digest(a, b)


def timing_jitter_small() -> None:
    """Small random delay to reduce timing side-channels between branches."""
    ms = int(getattr(settings, 'MOBILE_API_PASSWORD_RESET_TIMING_JITTER_MS', 35) or 35)
    if ms <= 0:
        return
    time.sleep(secrets.randbelow(ms + 1) / 1000.0)


def audit_password_reset_event(
    event: str,
    *,
    tenant_schema: str,
    email: str,
    request: Any = None,
    extra: str = '',
) -> None:
    """Structured audit line (no OTP, no full email)."""
    fp = email_fingerprint(email)
    ip = client_ip_from_request(request)
    logger.info(
        'mobile.pwdreset event=%s schema=%s email_fp=%s ip=%s %s',
        event,
        tenant_schema or '-',
        fp,
        ip or '-',
        (extra or '').strip(),
    )
