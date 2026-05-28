"""
mobile_api/job_detail/constants.py

Tunable limits for Job Detail (override via Django settings).
"""
from __future__ import annotations

from django.conf import settings


def _int_setting(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


JOB_DETAIL_ACTION_LOG_SCAN_LIMIT = _int_setting(
    'MOBILE_JOB_DETAIL_ACTION_LOG_SCAN_LIMIT',
    50,
)

# Embedded Job Detail GET timeline preview (reuses projection cache when loaded).
JOB_DETAIL_TIMELINE_PREVIEW_LIMIT = _int_setting(
    'MOBILE_JOB_DETAIL_TIMELINE_PREVIEW_LIMIT',
    20,
)

# Paginated timeline API (cursor); fetch limit+1 to detect has_more.
JOB_DETAIL_TIMELINE_PAGE_DEFAULT = _int_setting(
    'MOBILE_JOB_DETAIL_TIMELINE_PAGE_DEFAULT',
    20,
)
JOB_DETAIL_TIMELINE_PAGE_MAX = _int_setting(
    'MOBILE_JOB_DETAIL_TIMELINE_PAGE_MAX',
    50,
)

JOB_DETAIL_ETAG_ENABLED = bool(
    getattr(settings, 'MOBILE_JOB_DETAIL_ETAG_ENABLED', True)
)
