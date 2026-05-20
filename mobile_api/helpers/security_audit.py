"""
mobile_api/helpers/security_audit.py

Structured **security** logging for mobile auth (separate logger channel).

Use for tenant mismatches, token replay, OTP abuse signals, and other events
that security operations should monitor. Never log secrets, raw OTPs, or JWTs.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger('mobile_api.security')


def log_mobile_security_event(
    event: str,
    *,
    schema: str = '',
    user_id: str = '',
    ip: str = '',
    reason: str = '',
    extra: str = '',
) -> None:
    """
    Emit one structured line for SIEM / log aggregation.

    ``event`` should be a stable snake_case identifier (e.g. ``jwt_tenant_mismatch``).
    """
    logger.warning(
        'mobile.sec event=%s schema=%s user_id=%s ip=%s reason=%s %s',
        (event or 'unknown').strip()[:64],
        (schema or '-')[:128],
        (user_id or '-')[:64],
        (ip or '-')[:45],
        (reason or '-')[:200],
        (extra or '').strip()[:500],
    )


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
