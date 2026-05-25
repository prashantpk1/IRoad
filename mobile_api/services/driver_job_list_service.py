"""
mobile_api/services/driver_job_list_service.py

Job list module orchestration — secure context, summary, shared filter/order exports.

Does not assemble dashboard payloads; reuses dashboard **counters** and **security**
primitives only.
"""
from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.helpers.job_list_guards import reject_all_tab_without_queue
from mobile_api.helpers.job_list_observability import job_list_timer
from mobile_api.helpers.job_list_security import (
    SecureJobListContext,
    resolve_secure_job_list_context,
)
from mobile_api.helpers.job_list_filters import (
    JobListFilters,
    apply_job_filters,
    parse_job_list_filters,
)
from mobile_api.helpers.job_list_ordering import apply_job_ordering, parse_job_sort
from mobile_api.helpers.job_card_projections import project_route_from_shipment as build_job_route_projection
from mobile_api.services.driver_job_list_counters import (
    build_job_list_counters,
    project_job_list_summary_counters,
)
from mobile_api.services.driver_movement_list_service import (
    build_movement_job_card,
    list_driver_movements,
)
from mobile_api.services.driver_shipment_list_service import (
    build_shipment_job_card,
    list_driver_shipments,
)

__all__ = [
    'SecureJobListContext',
    'apply_job_filters',
    'apply_job_ordering',
    'build_job_route_projection',
    'build_job_summary',
    'build_job_list_counters',
    'build_movement_job_card',
    'build_shipment_job_card',
    'list_driver_movements',
    'list_driver_shipments',
    'resolve_secure_job_list_context',
]


# Re-exported from job_list_security (see that module for invariants).


def build_job_summary(
    *,
    driver,
    tenant_schema: str,
) -> dict[str, Any]:
    """
    Tab/badge counts for ``GET /driver/jobs/summary/``.

    Uses job-list counter aggregates (tab-aligned, independent of dashboard payload).
    Two DB round-trips — no per-row loops.
    """
    with job_list_timer(
        operation='summary_build',
        tenant_schema=tenant_schema,
        driver_id=str(driver.pk),
    ):
        with schema_context(tenant_schema):
            counters = build_job_list_counters(driver=driver)
    return {
        'counters': counters,
        'entity_types': ('shipment', 'movement'),
    }


def fetch_job_list_page(
    *,
    driver,
    tenant_schema: str,
    entity_type: str,
    request=None,
    filters: JobListFilters | None = None,
) -> dict[str, Any]:
    """
    Convenience entry: shipment or movement list metadata + queryset.

    ``entity_type``: ``shipment`` | ``movement``
    """
    if entity_type == 'movement':
        return list_driver_movements(
            driver=driver,
            tenant_schema=tenant_schema,
            request=request,
            filters=filters,
        )
    if entity_type == 'shipment':
        return list_driver_shipments(
            driver=driver,
            tenant_schema=tenant_schema,
            request=request,
            filters=filters,
        )
    return {
        'success': False,
        'error': _('mobile.validation.invalid_entity_type'),
    }
