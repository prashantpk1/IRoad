"""
mobile_api/helpers/job_list_ordering.py

Stable ordering for paginated driver job list feeds.
"""
from __future__ import annotations

from django.db.models import QuerySet

JobSortKey = str

VALID_SORT_KEYS: frozenset[str] = frozenset({
    'updated_desc',
    'updated_asc',
    'created_desc',
    'number_desc',
    'number_asc',
    'priority_desc',
    'status_asc',
})

DEFAULT_SORT: JobSortKey = 'updated_desc'


def parse_job_sort(request) -> JobSortKey:
    raw = ''
    if request is not None:
        params = getattr(request, 'query_params', None) or {}
        raw = (params.get('sort') or params.get('ordering') or '').strip().lower()
    if raw in VALID_SORT_KEYS:
        return raw
    return DEFAULT_SORT


def _priority_ordering_shipment(queryset: QuerySet) -> QuerySet:
    """Index-friendly ``priority_desc`` via persisted ``mobile_operational_rank``."""
    return queryset.order_by(
        'mobile_operational_rank',
        '-updated_at',
        '-created_at',
        'shipment_id',
    )


def apply_job_ordering(
    queryset: QuerySet,
    *,
    entity_type: str,
    sort: JobSortKey | None = None,
) -> QuerySet:
    """Apply operationally meaningful ordering for mobile list cards."""
    key = sort or DEFAULT_SORT
    if entity_type == 'shipment':
        if key == 'priority_desc':
            return _priority_ordering_shipment(queryset)
        if key == 'status_asc':
            return queryset.order_by('shipment_status', '-updated_at', 'shipment_no')
        if key == 'updated_asc':
            return queryset.order_by('updated_at', 'created_at', 'shipment_no')
        if key == 'created_desc':
            return queryset.order_by('-created_at', '-updated_at', 'shipment_no')
        if key == 'number_desc':
            return queryset.order_by('-shipment_no')
        if key == 'number_asc':
            return queryset.order_by('shipment_no')
        return queryset.order_by('-updated_at', '-created_at', 'shipment_no')

    if key == 'status_asc':
        return queryset.order_by('status', '-updated_at', 'movement_no')
    if key == 'updated_asc':
        return queryset.order_by('updated_at', 'created_at', 'movement_no')
    if key == 'created_desc':
        return queryset.order_by('-created_at', '-updated_at', 'movement_no')
    if key == 'number_desc':
        return queryset.order_by('-movement_no')
    if key == 'number_asc':
        return queryset.order_by('movement_no')
    return queryset.order_by('-updated_at', '-created_at', 'movement_no')
