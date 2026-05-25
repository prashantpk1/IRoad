"""
mobile_api/helpers/job_detail_guards.py

Production caps for job detail reads and timeline feeds.
"""
from __future__ import annotations

from django.conf import settings
from django.utils.translation import gettext as _


def job_detail_max_response_bytes() -> int:
    return int(
        getattr(settings, 'MOBILE_API_JOBS_MAX_RESPONSE_BYTES', 524288) or 524288
    )


def job_detail_strict_payload() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_STRICT_PAYLOAD', True))


def job_detail_enforce_payload_limit() -> bool:
    return bool(getattr(settings, 'MOBILE_API_JOBS_ENFORCE_PAYLOAD_LIMIT', True))


def job_detail_log_scan_limit() -> int:
    """Max action logs scanned for execution-state reconciliation on detail reads."""
    return max(
        20,
        min(
            300,
            int(getattr(settings, 'MOBILE_JOB_DETAIL_LOG_SCAN_LIMIT', 120) or 120),
        ),
    )


def job_detail_timeline_max_items() -> int:
    """Hard cap on timeline page rows (defense in depth beyond page_size)."""
    return max(
        1,
        min(
            50,
            int(getattr(settings, 'MOBILE_JOB_TIMELINE_MAX_PAGE_SIZE', 50) or 50),
        ),
    )


def enforce_detail_payload_size(
    payload: dict | list,
    *,
    operation: str,
) -> tuple[dict | list | None, str | None]:
    """
    Reject oversized detail/timeline JSON when strict payload mode is on.

    Returns ``(payload, None)`` or ``(None, error_code)``.
    """
    if not job_detail_enforce_payload_limit():
        return payload, None

    from mobile_api.helpers.job_list_observability import estimate_payload_bytes

    cap = job_detail_max_response_bytes()
    size = estimate_payload_bytes(payload if isinstance(payload, list) else [payload])
    if size <= cap:
        return payload, None
    if job_detail_strict_payload():
        return None, 'job_detail_payload_too_large'
    return payload, None


def validate_timeline_page_size(page_size: int) -> int:
    """Clamp timeline page size to configured max."""
    return max(1, min(page_size, job_detail_timeline_max_items()))
