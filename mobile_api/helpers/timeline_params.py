"""
Query params for job detail timeline feeds.
"""

from __future__ import annotations

from django.conf import settings


def timeline_default_page_size() -> int:
    return int(getattr(settings, 'MOBILE_JOB_TIMELINE_DEFAULT_PAGE_SIZE', 20) or 20)


def timeline_max_page_size() -> int:
    return int(getattr(settings, 'MOBILE_JOB_TIMELINE_MAX_PAGE_SIZE', 50) or 50)


def timeline_media_per_log() -> int:
    return int(getattr(settings, 'MOBILE_JOB_TIMELINE_MEDIA_PER_LOG', 3) or 3)


def resolve_timeline_page_size(request) -> int:
    from mobile_api.helpers.job_detail_guards import validate_timeline_page_size

    raw = None
    if request is not None:
        params = getattr(request, 'query_params', None) or {}
        raw = params.get('page_size')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = timeline_default_page_size()
    return validate_timeline_page_size(max(1, min(value, timeline_max_page_size())))
