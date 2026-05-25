"""
mobile_api/helpers/job_list_filter_service.py

Central driver-scoped job list pipeline: scope → tab/queue → search → dates → sort.
"""
from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from mobile_api.helpers.job_list_dates import (
    JobListDateRange,
    apply_job_date_filters,
    parse_date_field_param,
    parse_job_list_date_range,
)
from mobile_api.helpers.job_list_filters import (
    JobEntityType,
    JobListFilters,
    apply_job_filters,
)
from mobile_api.helpers.job_list_action_aggregation import job_list_include_actions
from mobile_api.helpers.job_list_performance import job_list_page_action_batch_enabled
from mobile_api.helpers.job_list_ordering import JobSortKey, apply_job_ordering
from mobile_api.helpers.job_list_query import (
    base_movement_job_queryset,
    base_shipment_job_queryset,
)


def build_driver_job_list_queryset(
    *,
    driver,
    entity_type: JobEntityType,
    filters: JobListFilters,
    sort: JobSortKey,
    date_field: str | None = None,
    include_actions: bool = True,
) -> QuerySet:
    """
    Assemble an optimized, driver-scoped queryset ready for ``MobileApiPagination``.

    Order of application (planner-friendly):
    1. Driver scope + ``only`` / ``select_related`` (base queryset)
    2. Tab + operational queue (status indexes)
    3. Search (prefix / subquery — no ``icontains`` on list paths)
    4. Date range (``updated_at`` or operational date)
    5. Sort (stable tie-breakers)
    """
    if entity_type == 'shipment':
        qs = base_shipment_job_queryset(driver)
    else:
        qs = base_movement_job_queryset(driver)

    qs = apply_job_filters(
        qs,
        entity_type=entity_type,
        filters=filters,
        driver=driver,
    )

    resolved_field = date_field or filters.date_field
    date_range = parse_job_list_date_range(
        date_from=filters.date_from,
        date_to=filters.date_to,
        date_field=resolved_field,  # type: ignore[arg-type]
    )
    qs = apply_job_date_filters(qs, entity_type=entity_type, date_range=date_range)
    qs = apply_job_ordering(qs, entity_type=entity_type, sort=sort)
    # Latest-action: batched after pagination (see job_list_page_action_batch_enabled).
    # Legacy path annotates subquery on full queryset — slower COUNT/LIST.
    if include_actions and not job_list_page_action_batch_enabled():
        from mobile_api.helpers.job_list_action_aggregation import (
            annotate_job_list_latest_log_id,
        )

        qs = annotate_job_list_latest_log_id(
            qs,
            entity_type=entity_type,  # type: ignore[arg-type]
            driver=driver,
        )
    return qs


def build_job_list_response_meta(
    filters: JobListFilters,
    *,
    sort: str,
    entity_type: str,
    locked_tab: str | None = None,
    locked_queue: str | None = None,
    date_field: str | None = None,
    include_actions: bool = True,
    request=None,
) -> dict[str, Any]:
    """Pagination meta echoing applied filters (mobile contract)."""
    field = date_field or filters.date_field
    base: dict[str, Any] = {
        'tab': filters.tab,
        'queue': filters.queue,
        'sort': sort,
        'entity_type': entity_type,
        'tab_locked': bool(locked_tab),
        'queue_locked': bool(locked_queue),
        'search': filters.search or '',
        'date_from': filters.date_from or '',
        'date_to': filters.date_to or '',
        'date_field': field,
    }
    base['include_actions'] = include_actions
    if request is not None:
        from mobile_api.helpers.job_list_guards import validate_mobile_list_params

        base.update(validate_mobile_list_params(request))
    return base


def resolve_job_list_include_actions(request) -> bool:
    return job_list_include_actions(request)


def parse_filters_and_dates_from_request(
    request,
    *,
    parse_filters_fn,
    locked_tab=None,
    locked_queue=None,
):
    """Combine filter parser + ``date_field`` query param."""
    filters = parse_filters_fn(
        request,
        locked_tab=locked_tab,
        locked_queue=locked_queue,
    )
    date_field = parse_date_field_param(request)
    return filters, date_field
