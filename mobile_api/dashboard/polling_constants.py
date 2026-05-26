"""
mobile_api/dashboard/polling_constants.py

Tunable limits for dashboard polling scalability (override via Django settings).
"""
from __future__ import annotations

from django.conf import settings


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _bool_setting(name: str, default: bool) -> bool:
    return bool(getattr(settings, name, default))


# Server-side projection cache (workflow / POD / job cards — not auth).
DASHBOARD_CACHE_ENABLED = _bool_setting('MOBILE_DASHBOARD_CACHE_ENABLED', True)
DASHBOARD_CACHE_TTL_SECONDS = _int_setting('MOBILE_DASHBOARD_CACHE_TTL_SECONDS', 30)

# Selector bounds — avoid full-history scans per poll.
DASHBOARD_BOOKING_CANDIDATE_LIMIT = _int_setting(
    'MOBILE_DASHBOARD_BOOKING_CANDIDATE_LIMIT',
    25,
)
DASHBOARD_MOVEMENT_CANDIDATE_LIMIT = _int_setting(
    'MOBILE_DASHBOARD_MOVEMENT_CANDIDATE_LIMIT',
    20,
)
DASHBOARD_MOVEMENT_LOOKBACK_DAYS = _int_setting(
    'MOBILE_DASHBOARD_MOVEMENT_LOOKBACK_DAYS',
    90,
)

# Single bounded Action Log scan per dashboard request (reconcile + timeline + POD).
DASHBOARD_ACTION_LOG_SCAN_LIMIT = _int_setting(
    'MOBILE_DASHBOARD_ACTION_LOG_SCAN_LIMIT',
    50,
)

# ETag / If-None-Match (304) for unchanged dashboard payloads.
DASHBOARD_ETAG_ENABLED = _bool_setting('MOBILE_DASHBOARD_ETAG_ENABLED', True)

CACHE_KEY_PREFIX = 'mobile_dashboard:v1'
