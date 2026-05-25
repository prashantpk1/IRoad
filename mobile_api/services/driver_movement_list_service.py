"""
mobile_api/services/driver_movement_list_service.py

Paginated driver-scoped movement job list (operational queue).
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.helpers.job_card_projections import build_movement_job_card_projection
from mobile_api.helpers.job_list_action_aggregation import (
    get_row_latest_action_summary,
    get_row_next_action_hint,
)
from mobile_api.helpers.job_list_filter_service import (
    build_driver_job_list_queryset,
    resolve_job_list_include_actions,
)
from mobile_api.helpers.job_list_filters import (
    JobListFilters,
    JobListTab,
    JobQueueFilter,
    movement_list_meta,
    parse_movement_job_list_filters,
)
from mobile_api.helpers.job_list_guards import reject_all_tab_without_queue
from mobile_api.helpers.job_list_ordering import parse_job_sort


def build_movement_job_card(movement, *, request=None) -> dict[str, Any]:
    """Lightweight movement job card (batched action fields when hydrated)."""
    return build_movement_job_card_projection(
        movement,
        request=request,
        latest_action_summary=get_row_latest_action_summary(movement),
        next_action_hint=get_row_next_action_hint(movement),
    )


def list_driver_movements(
    *,
    driver,
    tenant_schema: str,
    request=None,
    filters: JobListFilters | None = None,
    default_tab: JobListTab = 'active',
    locked_tab: JobListTab | None = None,
    locked_queue: JobQueueFilter | None = None,
) -> dict[str, Any]:
    """
    Return a filtered, ordered queryset for movement job cards.

    Views paginate ``queryset`` and map rows with ``build_movement_job_card``.
    """
    include_actions = resolve_job_list_include_actions(request)
    resolved_filters = filters
    if resolved_filters is None:
        resolved_filters = parse_movement_job_list_filters(
            request,
            default_tab=default_tab,
            locked_tab=locked_tab,
            locked_queue=locked_queue,
        )
    sort_key = parse_job_sort(request)
    tab_err = reject_all_tab_without_queue(resolved_filters.tab, entity_type='movement')
    if tab_err:
        return {
            'success': False,
            'error': tab_err,
            'code': 'tab_all_not_allowed',
        }

    with schema_context(tenant_schema):
        qs = build_driver_job_list_queryset(
            driver=driver,
            entity_type='movement',
            filters=resolved_filters,
            sort=sort_key,
            include_actions=include_actions,
        )

    return {
        'success': True,
        'queryset': qs,
        'entity_type': 'movement',
        'include_actions': include_actions,
        'meta': movement_list_meta(
            resolved_filters,
            sort=sort_key,
            locked_tab=locked_tab,
            locked_queue=locked_queue,
            include_actions=include_actions,
            request=request,
        ),
    }
