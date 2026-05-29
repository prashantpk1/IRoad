"""
mobile_api/history/constants.py

Tunable limits for driver History APIs.
"""
from __future__ import annotations

from django.conf import settings


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


# Max completed shipments returned in one History list response (no cursor pagination).
HISTORY_LIST_MAX_RESULTS = _int_setting('MOBILE_HISTORY_LIST_MAX_RESULTS', 200)
HISTORY_ACTION_LOG_SCAN_LIMIT = _int_setting('MOBILE_HISTORY_ACTION_LOG_SCAN_LIMIT', 100)
HISTORY_DETAIL_TIMELINE_LIMIT = _int_setting('MOBILE_HISTORY_DETAIL_TIMELINE_LIMIT', 100)
