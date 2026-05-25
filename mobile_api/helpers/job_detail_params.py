"""Query params for job detail snapshot endpoints."""

from __future__ import annotations

from django.conf import settings


def job_detail_timeline_preview_limit() -> int:
    return max(
        1,
        min(
            50,
            int(getattr(settings, 'MOBILE_JOB_DETAIL_TIMELINE_PREVIEW_LIMIT', 15) or 15),
        ),
    )


def parse_job_detail_include_flags(request) -> dict[str, bool]:
    """``include_timeline`` / ``include_actions`` — default on unless ``=0``."""
    params = getattr(request, 'query_params', None) or {}

    def _flag(name: str, default: bool) -> bool:
        raw = (params.get(name) or '').strip().lower()
        if raw in ('0', 'false', 'no', 'off'):
            return False
        if raw in ('1', 'true', 'yes', 'on'):
            return True
        return default

    return {
        'include_timeline': _flag(
            'include_timeline',
            bool(getattr(settings, 'MOBILE_JOB_DETAIL_INCLUDE_TIMELINE_DEFAULT', True)),
        ),
        'include_actions': _flag(
            'include_actions',
            bool(getattr(settings, 'MOBILE_JOB_DETAIL_INCLUDE_ACTIONS_DEFAULT', True)),
        ),
    }
