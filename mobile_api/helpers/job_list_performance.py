"""
mobile_api/helpers/job_list_performance.py

Query budget targets and performance toggles for driver job list feeds.
"""
from __future__ import annotations

from django.conf import settings

# Per paginated list request (default page_size=10, include_actions=True).
JOB_LIST_QUERY_BUDGET = {
    'list_page': 1,  # ORM page slice (+ optional COUNT)
    'count': 1,  # Paginator COUNT (skippable via include_total=0)
    'latest_action_batch': 1,  # DISTINCT ON page parent ids (PostgreSQL)
    'sanitize_scope': 0,  # 0 when MOBILE_API_JOBS_ENFORCE_OWNERSHIP_SANITIZE=False
}
# Summary endpoint (separate from list).
JOB_SUMMARY_QUERY_BUDGET = {
    'shipment_aggregate': 1,
    'movement_aggregate': 1,
}


def job_list_page_action_batch_enabled() -> bool:
    """
    When True (default), latest-action loads **after** pagination via one
    ``DISTINCT ON`` query — no correlated subquery on the full filtered queryset.
    """
    return bool(
        getattr(settings, 'MOBILE_JOB_LIST_PAGE_ACTION_BATCH', True)
    )


def job_list_fast_serialize_enabled() -> bool:
    """Skip DRF re-validation when cards are built from trusted projections."""
    return bool(
        getattr(settings, 'MOBILE_JOB_LIST_FAST_SERIALIZE', True)
    )


def job_list_include_total_default() -> bool:
    """Default **False** — mobile polling must opt in with ``include_total=1``."""
    return bool(
        getattr(settings, 'MOBILE_JOB_LIST_INCLUDE_TOTAL_DEFAULT', False)
    )


def job_list_max_page_size() -> int:
    """Bounded page size for job lists (stricter than global ``MOBILE_API_MAX_PAGE_SIZE``)."""
    from mobile_api.helpers.job_list_guards import job_list_max_page_size as _guarded

    return _guarded()


def resolve_include_total(request) -> bool:
    """Query ``include_total=0`` skips expensive ``COUNT(*)`` on large lists."""
    if request is None:
        return job_list_include_total_default()
    params = getattr(request, 'query_params', None) or {}
    raw = (params.get('include_total') or '').strip().lower()
    if raw in ('0', 'false', 'no', 'off'):
        return False
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    return job_list_include_total_default()
