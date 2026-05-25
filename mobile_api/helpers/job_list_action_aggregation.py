"""
mobile_api/helpers/job_list_action_aggregation.py

Batched latest-action loading for paginated job list feeds.

Query budget per list page (N = page size, default ≤10):
  - 1 subquery annotation on the list queryset (planner uses shipment/movement indexes)
  - 1 bulk fetch for distinct latest log rows (+ operation_action join)
  - 0 per-row ``fetch_latest_action_log()`` calls
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.db.models import OuterRef, QuerySet, Subquery

from mobile_api.helpers.job_list_next_action import (
    batch_build_movement_next_action_hints,
    batch_build_shipment_next_action_hints,
)
from mobile_api.helpers.job_list_performance import job_list_page_action_batch_enabled

JobListEntityType = Literal['shipment', 'movement']

_ACTION_LOG_LIST_ONLY = (
    'log_id',
    'log_no',
    'log_date',
    'operation_action_id',
    'shipment_id',
    'truck_movement_id',
)

_OPERATION_ACTION_ONLY = (
    'action_id',
    'action_code',
    'english_label',
    'arabic_label',
)

# Attached to ORM rows after pagination hydrate.
_LATEST_ACTION_ATTR = '_job_list_latest_action_summary'
_NEXT_ACTION_ATTR = '_job_list_next_action_hint'


def job_list_include_actions(request=None) -> bool:
    """Feature flag: settings default, optional ``include_actions=0`` query override."""
    default = bool(
        getattr(settings, 'MOBILE_JOB_LIST_INCLUDE_ACTIONS', True)
    )
    if request is None:
        return default
    params = getattr(request, 'query_params', None) or {}
    raw = (params.get('include_actions') or '').strip().lower()
    if raw in ('0', 'false', 'no', 'off'):
        return False
    if raw in ('1', 'true', 'yes', 'on'):
        return True
    return default


def _driver_pk(driver) -> Any:
    return getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)


def _latest_log_id_subquery(*, driver, link_field: str) -> Subquery:
    """
    Latest log id per parent row (shipment or movement).

    Uses indexes:
    - ``tenant_oal_ship_drv_date_idx`` (shipment + driver)
    - ``tenant_oal_move_drv_date_idx`` (movement + driver) when migrated
    """
    from tenant_workspace.models import TenantOperationActionLog

    return Subquery(
        TenantOperationActionLog.objects.filter(
            driver_id=_driver_pk(driver),
            **{link_field: OuterRef('pk')},
        )
        .order_by('-log_date', '-created_at')
        .values('log_id')[:1]
    )


def annotate_shipment_list_latest_log_id(queryset: QuerySet, *, driver) -> QuerySet:
    """Annotate each shipment with ``latest_action_log_id`` (single subquery per row)."""
    return queryset.annotate(
        latest_action_log_id=_latest_log_id_subquery(
            driver=driver,
            link_field='shipment_id',
        ),
    )


def annotate_movement_list_latest_log_id(queryset: QuerySet, *, driver) -> QuerySet:
    """Annotate each movement with ``latest_action_log_id``."""
    return queryset.annotate(
        latest_action_log_id=_latest_log_id_subquery(
            driver=driver,
            link_field='truck_movement_id',
        ),
    )


def annotate_job_list_latest_log_id(
    queryset: QuerySet,
    *,
    entity_type: JobListEntityType,
    driver,
) -> QuerySet:
    if entity_type == 'shipment':
        return annotate_shipment_list_latest_log_id(queryset, driver=driver)
    return annotate_movement_list_latest_log_id(queryset, driver=driver)


def project_action_log_card_summary(log_row, request=None) -> dict[str, Any] | None:
    """Lightweight latest-action projection for job cards."""
    if log_row is None:
        return None
    from mobile_api.services.driver_dashboard_current_job import (
        project_latest_action_summary,
    )

    block = project_latest_action_summary(log_row, request)
    if not block:
        return None
    return {
        'log_id': block.get('log_id'),
        'log_no': block.get('log_no'),
        'log_date': block.get('log_date'),
        'action_code': block.get('action_code'),
        'action_label': block.get('action_label'),
    }


def _latest_logs_distinct_on(
    *,
    driver,
    parent_field: str,
    parent_ids: list,
) -> list:
    """
    One query: latest log per parent id (PostgreSQL ``DISTINCT ON``).

    ``parent_field``: ``shipment_id`` or ``truck_movement_id``.
    """
    if not parent_ids:
        return []
    from tenant_workspace.models import TenantOperationActionLog

    return list(
        TenantOperationActionLog.objects.filter(
            driver_id=_driver_pk(driver),
            **{f'{parent_field}__in': parent_ids},
        )
        .only(*_ACTION_LOG_LIST_ONLY)
        .select_related('operation_action')
        .order_by(parent_field, '-log_date', '-created_at')
        .distinct(parent_field)
    )


def batch_fetch_latest_action_by_shipment_ids(
    *,
    driver,
    shipment_ids: list,
    request=None,
) -> dict[str, dict[str, Any]]:
    """Map ``str(shipment_id)`` → latest action summary for current page."""
    rows = _latest_logs_distinct_on(
        driver=driver,
        parent_field='shipment_id',
        parent_ids=shipment_ids,
    )
    if driver is not None:
        from mobile_api.helpers.job_list_security import assert_job_list_action_logs_owned

        rows = assert_job_list_action_logs_owned(driver=driver, log_rows=rows)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = getattr(row, 'shipment_id', None)
        if not sid:
            continue
        summary = project_action_log_card_summary(row, request)
        if summary:
            out[str(sid)] = summary
    return out


def batch_fetch_latest_action_by_movement_ids(
    *,
    driver,
    movement_ids: list,
    request=None,
) -> dict[str, dict[str, Any]]:
    """Map ``str(movement_id)`` → latest action summary for current page."""
    rows = _latest_logs_distinct_on(
        driver=driver,
        parent_field='truck_movement_id',
        parent_ids=movement_ids,
    )
    if driver is not None:
        from mobile_api.helpers.job_list_security import assert_job_list_action_logs_owned

        rows = assert_job_list_action_logs_owned(driver=driver, log_rows=rows)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        mid = getattr(row, 'truck_movement_id', None)
        if not mid:
            continue
        summary = project_action_log_card_summary(row, request)
        if summary:
            out[str(mid)] = summary
    return out


def batch_fetch_latest_action_summaries(
    log_ids: list,
    *,
    request=None,
    driver=None,
) -> dict[str, dict[str, Any]]:
    """
    One query for all latest logs on the current page.

    Returns map keyed by ``str(log_id)``.
    """
    normalized: list[UUID] = []
    for raw in log_ids:
        if not raw:
            continue
        try:
            normalized.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return {}

    from tenant_workspace.models import TenantOperationActionLog

    rows = list(
        TenantOperationActionLog.objects.filter(log_id__in=normalized)
        .only(*_ACTION_LOG_LIST_ONLY)
        .select_related('operation_action')
    )
    if driver is not None:
        from mobile_api.helpers.job_list_security import assert_job_list_action_logs_owned

        rows = assert_job_list_action_logs_owned(driver=driver, log_rows=rows)
    # Trim joined action columns when only() is used on parent.
    for row in rows:
        action = getattr(row, 'operation_action', None)
        if action is not None:
            for name in _OPERATION_ACTION_ONLY:
                getattr(action, name, None)

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        summary = project_action_log_card_summary(row, request)
        if summary:
            out[str(row.log_id)] = summary
    return out


def _collect_latest_log_ids(rows: list) -> list:
    ids = []
    seen: set[str] = set()
    for row in rows:
        log_id = getattr(row, 'latest_action_log_id', None)
        if not log_id:
            continue
        key = str(log_id)
        if key in seen:
            continue
        seen.add(key)
        ids.append(log_id)
    return ids


def hydrate_job_list_page_actions(
    rows: list,
    *,
    entity_type: JobListEntityType,
    driver,
    request=None,
    include_actions: bool = True,
) -> list:
    """
    Attach ``_job_list_latest_action_summary`` and ``_job_list_next_action_hint``
    on each row (batched — no per-row log queries).
    """
    if not rows:
        return rows

    if include_actions:
        if job_list_page_action_batch_enabled():
            if entity_type == 'shipment':
                parent_ids = [
                    getattr(r, 'shipment_id', None) or getattr(r, 'pk', None)
                    for r in rows
                ]
                by_parent = batch_fetch_latest_action_by_shipment_ids(
                    driver=driver,
                    shipment_ids=[x for x in parent_ids if x],
                    request=request,
                )
                for row in rows:
                    sid = str(
                        getattr(row, 'shipment_id', None) or getattr(row, 'pk', '')
                    )
                    setattr(row, _LATEST_ACTION_ATTR, by_parent.get(sid))
            else:
                parent_ids = [
                    getattr(r, 'movement_id', None) or getattr(r, 'pk', None)
                    for r in rows
                ]
                by_parent = batch_fetch_latest_action_by_movement_ids(
                    driver=driver,
                    movement_ids=[x for x in parent_ids if x],
                    request=request,
                )
                for row in rows:
                    mid = str(
                        getattr(row, 'movement_id', None) or getattr(row, 'pk', '')
                    )
                    setattr(row, _LATEST_ACTION_ATTR, by_parent.get(mid))
        else:
            summaries = batch_fetch_latest_action_summaries(
                _collect_latest_log_ids(rows),
                request=request,
                driver=driver,
            )
            for row in rows:
                log_id = getattr(row, 'latest_action_log_id', None)
                summary = summaries.get(str(log_id)) if log_id else None
                setattr(row, _LATEST_ACTION_ATTR, summary)
    else:
        for row in rows:
            setattr(row, _LATEST_ACTION_ATTR, None)

    if entity_type == 'shipment':
        hint_map = batch_build_shipment_next_action_hints(rows)
        for row in rows:
            sid = str(getattr(row, 'shipment_id', None) or getattr(row, 'pk', ''))
            setattr(row, _NEXT_ACTION_ATTR, hint_map.get(sid))
    else:
        hint_map = batch_build_movement_next_action_hints(rows)
        for row in rows:
            mid = str(getattr(row, 'movement_id', None) or getattr(row, 'pk', ''))
            setattr(row, _NEXT_ACTION_ATTR, hint_map.get(mid))

    return rows


def _hydrated_attr(row, name: str) -> Any:
    """Read hydrate attrs only when explicitly set (MagicMock-safe)."""
    cache = getattr(row, '__dict__', None)
    if isinstance(cache, dict) and name in cache:
        return cache[name]
    return None


def get_row_latest_action_summary(row) -> dict[str, Any] | None:
    return _hydrated_attr(row, _LATEST_ACTION_ATTR)


def get_row_next_action_hint(row) -> str | None:
    return _hydrated_attr(row, _NEXT_ACTION_ATTR)


def build_shipment_action_snapshot(
    shipment,
    *,
    request=None,
    latest_action_summary: dict[str, Any] | None = None,
    next_action_hint: str | None = None,
) -> dict[str, Any]:
    """Shipment action summary block for job cards."""
    return {
        'latest_action_summary': latest_action_summary,
        'next_action_hint': next_action_hint,
    }


def build_movement_action_snapshot(
    movement,
    *,
    request=None,
    latest_action_summary: dict[str, Any] | None = None,
    next_action_hint: str | None = None,
) -> dict[str, Any]:
    """Movement action summary block for job cards."""
    return {
        'latest_action_summary': latest_action_summary,
        'next_action_hint': next_action_hint,
    }
