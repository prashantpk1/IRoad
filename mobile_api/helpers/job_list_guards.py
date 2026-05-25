"""
mobile_api/helpers/job_list_guards.py

Production safeguards: pagination depth, search bounds, filter validation.
"""
from __future__ import annotations

from django.conf import settings
from django.utils.translation import gettext as _

from mobile_api.helpers.job_list_search import normalize_search_term

MAX_SEARCH_LENGTH = 64


def job_list_max_page_size() -> int:
    return max(1, int(getattr(settings, 'MOBILE_API_JOBS_MAX_PAGE_SIZE', 50) or 50))


def job_list_max_page_number() -> int:
    return max(1, int(getattr(settings, 'MOBILE_API_JOBS_MAX_PAGE', 500) or 500))


def job_list_max_offset_rows() -> int:
    return max(
        job_list_max_page_size(),
        int(getattr(settings, 'MOBILE_API_JOBS_MAX_OFFSET_ROWS', 5000) or 5000),
    )


def clamp_page_size(raw_size) -> int:
    try:
        size = int(raw_size or 10)
    except (TypeError, ValueError):
        size = 10
    return min(max(1, size), job_list_max_page_size())


def offset_pagination_allowed() -> bool:
    """When False (production default), ``page`` query param is rejected."""
    return bool(getattr(settings, 'MOBILE_API_JOBS_ALLOW_OFFSET_PAGINATION', False))


def reject_offset_pagination(request) -> str | None:
    if offset_pagination_allowed():
        return None
    if request is None:
        return None
    params = getattr(request, 'query_params', None) or {}
    raw = (params.get('page') or '').strip()
    if raw:
        return _('mobile.jobs.offset_not_allowed')
    return None


def validate_pagination_request(*, page: int, page_size: int) -> str | None:
    """
    Return error message if pagination exceeds production limits, else None.
    """
    if page < 1:
        return _('mobile.jobs.pagination_invalid_page')
    if page > job_list_max_page_number():
        return _('mobile.jobs.pagination_page_too_large')
    offset = (page - 1) * page_size
    if offset >= job_list_max_offset_rows():
        return _('mobile.jobs.pagination_offset_too_large')
    return None


def sanitize_search_term(term: str | None) -> str:
    """Bound search length; strip control characters."""
    normalized = normalize_search_term(term)
    if len(normalized) > MAX_SEARCH_LENGTH:
        return normalized[:MAX_SEARCH_LENGTH]
    return ''.join(ch for ch in normalized if ch.isprintable())


def job_list_strict_payload() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_STRICT_PAYLOAD', True))


def job_list_enforce_payload_limit() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_ENFORCE_PAYLOAD_LIMIT', True))


def enforce_payload_limit(items: list) -> tuple[list | None, str | None, str | None]:
    """
    Hard cap on serialized list payload size.

    Strict mode (default): reject entire response when over cap.
    """
    from mobile_api.helpers.job_list_observability import estimate_payload_bytes

    cap = int(getattr(settings, 'MOBILE_API_JOBS_MAX_RESPONSE_BYTES', 524288) or 524288)
    if not job_list_enforce_payload_limit():
        return items, None, None
    size = estimate_payload_bytes(items)
    if size <= cap:
        return items, None, None
    if not items:
        return None, _('mobile.jobs.payload_empty'), 'job_list_payload_too_large'
    if job_list_strict_payload():
        return None, _('mobile.jobs.payload_too_large'), 'job_list_payload_too_large'
    trimmed: list = []
    for item in items:
        trial = trimmed + [item]
        if estimate_payload_bytes(trial) > cap:
            break
        trimmed = trial
    if not trimmed:
        return None, _('mobile.jobs.payload_too_large'), 'job_list_payload_too_large'
    return trimmed, _('mobile.jobs.payload_truncated'), 'job_list_payload_truncated'


def reject_all_tab_without_queue(tab: str, *, entity_type: str) -> str | None:
    """
    Discourage unbounded ``tab=all`` on large tenants without narrowing.

    Returns error message or None.
    """
    if not getattr(settings, 'MOBILE_API_JOBS_DISALLOW_TAB_ALL', False):
        return None
    if tab != 'all':
        return None
    return _('mobile.jobs.tab_all_not_allowed')


def validate_mobile_list_params(request) -> dict[str, str]:
    """
    Mobile polling contract warnings (returned in list meta by views).

    Keys: ``polling_warnings`` comma-separated codes for client telemetry.
    """
    warnings: list[str] = []
    if request is None:
        return {}
    params = getattr(request, 'query_params', None) or {}
    if (params.get('include_total') or '').strip().lower() in ('1', 'true', 'yes', 'on'):
        warnings.append('include_total_on_poll')
    try:
        size = int(params.get('page_size') or 0)
        if size > job_list_max_page_size():
            warnings.append('page_size_capped')
    except (TypeError, ValueError):
        pass
    if (params.get('page') or '').strip() and not offset_pagination_allowed():
        warnings.append('offset_rejected')
    if not (params.get('cursor') or '').strip() and not (params.get('page') or '').strip():
        warnings.append('use_cursor_pagination')
    if warnings:
        return {'polling_warnings': ','.join(warnings)}
    return {}
