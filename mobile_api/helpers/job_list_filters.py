"""
mobile_api/helpers/job_list_filters.py

Tab and query-param filters for driver job list feeds (shipments + movements).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.db.models import Q, QuerySet

from mobile_api.helpers.job_list_dates import parse_date_field_param
from mobile_api.helpers.job_list_guards import sanitize_search_term
from mobile_api.helpers.job_list_search import (
    is_searchable,
    movement_job_search_q,
    shipment_job_search_q,
)

from mobile_api.helpers.dashboard_aggregations import (
    shipment_active_filter_q,
    shipment_cod_pending_filter_q,
    shipment_pod_pending_filter_q,
)
from mobile_api.helpers.operational_status import (
    SHIPMENT_CANCELLED_STATUSES,
    movement_empty_move_filter_q,
    movement_tab_filter_q,
    shipment_completed_statuses,
)

JobListTab = Literal['active', 'completed', 'cancelled', 'all']
JobEntityType = Literal['shipment', 'movement']
JobQueueFilter = Literal[
    'none',
    'pod_pending',
    'cod_pending',
    'delivery_pending',
    'pickup_pending',
    'empty_move',
]

VALID_TABS: frozenset[str] = frozenset({'active', 'completed', 'cancelled', 'all'})
VALID_QUEUES: frozenset[str] = frozenset({
    'none',
    'pod_pending',
    'cod_pending',
    'delivery_pending',
    'pickup_pending',
    'empty_move',
})


@dataclass(frozen=True)
class JobListFilters:
    """Parsed list request filters (driver scope applied separately)."""

    tab: JobListTab = 'active'
    queue: JobQueueFilter = 'none'
    search: str = ''
    date_from: str | None = None
    date_to: str | None = None
    date_field: str = 'updated'


def parse_job_list_filters(
    request,
    *,
    default_tab: JobListTab = 'active',
    default_queue: JobQueueFilter = 'none',
    locked_tab: JobListTab | None = None,
    locked_queue: JobQueueFilter | None = None,
) -> JobListFilters:
    """
    Read ``tab``, ``queue``, ``q``, ``date_from``, ``date_to`` from query params.

    When ``locked_tab`` / ``locked_queue`` are set (path-based list endpoints), query
    params cannot override those dimensions.
    """
    params = getattr(request, 'query_params', None) or {}
    if locked_tab:
        tab: JobListTab = locked_tab
    else:
        raw_tab = (params.get('tab') or default_tab or 'active').strip().lower()
        tab = raw_tab if raw_tab in VALID_TABS else 'active'  # type: ignore[assignment]

    if locked_queue:
        queue: JobQueueFilter = locked_queue
    else:
        raw_queue = (params.get('queue') or default_queue or 'none').strip().lower()
        queue = raw_queue if raw_queue in VALID_QUEUES else 'none'  # type: ignore[assignment]

    search = sanitize_search_term(params.get('q') or params.get('search'))
    date_from = (params.get('date_from') or '').strip() or None
    date_to = (params.get('date_to') or '').strip() or None
    date_field = parse_date_field_param(request) if request is not None else 'updated'
    return JobListFilters(
        tab=tab,
        queue=queue,
        search=search,
        date_from=date_from,
        date_to=date_to,
        date_field=date_field,
    )


def parse_shipment_job_list_filters(
    request,
    *,
    default_tab: JobListTab = 'active',
    locked_tab: JobListTab | None = None,
    locked_queue: JobQueueFilter | None = None,
) -> JobListFilters:
    """Shipment list filter parser (alias with shipment-oriented defaults)."""
    return parse_job_list_filters(
        request,
        default_tab=default_tab,
        default_queue='none',
        locked_tab=locked_tab,
        locked_queue=locked_queue,
    )


def parse_movement_job_list_filters(
    request,
    *,
    default_tab: JobListTab = 'active',
    locked_tab: JobListTab | None = None,
    locked_queue: JobQueueFilter | None = None,
) -> JobListFilters:
    """Movement list filter parser."""
    return parse_job_list_filters(
        request,
        default_tab=default_tab,
        default_queue='none',
        locked_tab=locked_tab,
        locked_queue=locked_queue,
    )


def movement_list_meta(
    filters: JobListFilters,
    *,
    sort: str,
    locked_tab: JobListTab | None = None,
    locked_queue: JobQueueFilter | None = None,
    include_actions: bool = True,
    request=None,
) -> dict[str, str | bool]:
    """Response meta for paginated movement job list envelopes."""
    from mobile_api.helpers.job_list_filter_service import build_job_list_response_meta

    return build_job_list_response_meta(
        filters,
        sort=sort,
        entity_type='movement',
        locked_tab=locked_tab,
        locked_queue=locked_queue,
        include_actions=include_actions,
        request=request,
    )


def shipment_list_meta(
    filters: JobListFilters,
    *,
    sort: str,
    locked_tab: JobListTab | None = None,
    locked_queue: JobQueueFilter | None = None,
    include_actions: bool = True,
    request=None,
) -> dict[str, str | bool]:
    """Response meta for paginated shipment job list envelopes."""
    from mobile_api.helpers.job_list_filter_service import build_job_list_response_meta

    return build_job_list_response_meta(
        filters,
        sort=sort,
        entity_type='shipment',
        locked_tab=locked_tab,
        locked_queue=locked_queue,
        include_actions=include_actions,
        request=request,
    )


def _shipment_tab_q(tab: JobListTab) -> Q:
    if tab == 'active':
        return shipment_active_filter_q()
    if tab == 'completed':
        return Q(shipment_status__in=shipment_completed_statuses())
    if tab == 'cancelled':
        return Q(shipment_status__in=SHIPMENT_CANCELLED_STATUSES)
    return Q()


def _movement_tab_q(tab: JobListTab) -> Q:
    return movement_tab_filter_q(tab)


def _shipment_queue_q(queue: JobQueueFilter) -> Q:
    from tenant_workspace.models import TenantShipment

    pod_compliant = TenantShipment.PodStatus.COMPLIANT
    collection_pending = TenantShipment.CollectionStatus.PENDING
    if queue == 'pod_pending':
        return shipment_pod_pending_filter_q(pod_compliant=pod_compliant)
    if queue == 'cod_pending':
        return shipment_cod_pending_filter_q(collection_pending=collection_pending)
    if queue == 'delivery_pending':
        return Q(shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY)
    if queue == 'pickup_pending':
        return Q(
            shipment_status__in=(
                TenantShipment.ShipmentStatus.LOADED,
                TenantShipment.ShipmentStatus.CREATED,
            )
        )
    return Q()


def _movement_queue_q(queue: JobQueueFilter) -> Q:
    if queue == 'empty_move':
        return movement_empty_move_filter_q()
    return Q()


def apply_job_filters(
    queryset: QuerySet,
    *,
    entity_type: JobEntityType,
    filters: JobListFilters,
    driver=None,
) -> QuerySet:
    """
    Apply tab, operational queue, and index-friendly search filters.

    Date filters are applied by ``job_list_filter_service`` (timestamp ranges).
    Caller must already scope queryset to the authenticated driver.
    """
    qs = queryset
    if entity_type == 'shipment':
        qs = qs.filter(_shipment_tab_q(filters.tab))
        if filters.queue != 'none':
            qs = qs.filter(_shipment_queue_q(filters.queue))
        if is_searchable(filters.search):
            qs = qs.filter(shipment_job_search_q(filters.search))
        return qs

    qs = qs.filter(_movement_tab_q(filters.tab))
    if filters.queue != 'none':
        qs = qs.filter(_movement_queue_q(filters.queue))
    if is_searchable(filters.search) and driver is not None:
        qs = qs.filter(movement_job_search_q(filters.search, driver=driver))
    elif is_searchable(filters.search):
        from mobile_api.helpers.job_list_search import _exact_code_q

        qs = qs.filter(_exact_code_q('movement_no', filters.search))
    return qs


def apply_job_filters_for_driver(
    queryset: QuerySet,
    *,
    entity_type: JobEntityType,
    filters: JobListFilters,
    driver,
) -> QuerySet:
    """Apply filters with driver context (movement search subquery)."""
    return apply_job_filters(
        queryset,
        entity_type=entity_type,
        filters=filters,
        driver=driver,
    )
