"""
mobile_api/helpers/login_throttle.py

Cache-backed **burst** limits for ``driver_login`` (per IP and per email
fingerprint) to slow credential-stuffing and password spraying before expensive
DB work. Complements per-user ``TenantUser.login_attempts`` lockout.

Cache read failures **allow** the request when ``MOBILE_API_LOGIN_BURST_FAIL_CLOSED_ON_CACHE_ERROR``
is False (default in DEBUG); in production defaults they **deny** so a broken
cache cannot disable abuse protection. Pair with DRF throttles on the view.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from mobile_api.helpers.password_reset_security import (
    client_ip_from_request,
    email_fingerprint,
)

logger = logging.getLogger('mobile_api')


def _window_seconds() -> int:
    return int(
        getattr(settings, 'MOBILE_API_LOGIN_BURST_WINDOW_SECONDS', 900) or 900,
    )


def _max_per_ip() -> int:
    return int(
        getattr(settings, 'MOBILE_API_LOGIN_BURST_MAX_PER_IP', 60) or 60,
    )


def _max_per_email_fp() -> int:
    return int(
        getattr(settings, 'MOBILE_API_LOGIN_BURST_MAX_PER_EMAIL', 25) or 25,
    )


def _cache_incr(key: str, timeout: int) -> int:
    try:
        from django.core.cache import cache

        raw = cache.get(key)
        n = int(raw) + 1 if raw is not None else 1
        cache.set(key, n, timeout=timeout)
        return n
    except Exception as exc:
        logger.warning('login_throttle cache incr failed key=%s: %s', key[:48], exc)
        return 0


def driver_login_burst_allow(
    *,
    email: str,
    request: Any,
) -> bool:
    """
    False when this login attempt should be rejected as over burst budget.

    Uses keys ``m_login:burst:ip:…`` and ``m_login:burst:em:…``.
    """
    try:
        from django.core.cache import cache

        window = _window_seconds()
        ip = client_ip_from_request(request) or 'unknown'
        fp = email_fingerprint(email)
        i_key = f'm_login:burst:ip:{ip}'
        e_key = f'm_login:burst:em:{fp}'
        if int(cache.get(i_key, 0) or 0) >= _max_per_ip():
            return False
        if int(cache.get(e_key, 0) or 0) >= _max_per_email_fp():
            return False
    except Exception as exc:
        logger.warning('login_throttle burst read failed: %s', exc)
        return not bool(
            getattr(
                settings,
                'MOBILE_API_LOGIN_BURST_FAIL_CLOSED_ON_CACHE_ERROR',
                False,
            )
        )
    return True


def driver_login_burst_record(*, email: str, request: Any) -> None:
    """Increment burst counters after a login **request** is accepted for processing."""
    window = _window_seconds()
    ip = client_ip_from_request(request) or 'unknown'
    fp = email_fingerprint(email)
    _cache_incr(f'm_login:burst:ip:{ip}', window)
    _cache_incr(f'm_login:burst:em:{fp}', window)
