"""
History Detail timeline — reuse Job Detail merge/sort so existing shipments
show the same performed steps (POD, unloading, COD, job close) as live jobs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_delivery_arrival_action,
    is_loading_action,
    is_pickup_action,
)
from mobile_api.helpers.job_action_resolver import (
    action_is_collect_payment,
    action_is_job_close,
)
from mobile_api.history.projections.history_milestone_resolver import (
    _tenant_schema_from_request,
    milestone_completed_for_history,
    pick_log_for_history_milestone,
    resolve_history_milestone_specs,
)
from mobile_api.history.selectors.order_type_resolver import resolve_order_type
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    filter_hidden_timeline_events,
    merge_actions_with_timeline_logs,
    sort_timeline_display_order,
)
from mobile_api.job_detail.timeline.timeline_service import JobDetailTimelineService
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_pod_upload_action,
    is_unloading_action,
)
from tenant_workspace.models import TenantShipment

_EARLIEST_STEP_KEYS = frozenset(
    {'pickup', 'loading', 'in_transit', 'delivery', 'pod', 'unloading', 'payment'},
)


def _classify_history_step_key(action: Any | None) -> str | None:
    if action is None:
        return None
    if action_is_job_close(action):
        return 'job_closed'
    if action_is_collect_payment(action):
        return 'payment'
    if is_pickup_action(action):
        return 'pickup'
    if is_loading_action(action):
        return 'loading'
    if is_delivery_arrival_action(action):
        return 'delivery'
    if is_pod_upload_action(action) or bool(getattr(action, 'auto_pod_post', False)):
        return 'pod'
    if is_unloading_action(action):
        return 'unloading'
    from iroad_tenants.operation_execution import action_matches

    if action_matches(
        action,
        'in transit',
        'depart',
        'a5',
        'action 5',
        'shipment in transit',
    ):
        return 'in_transit'
    return None


def _resolve_action_for_event(event: dict[str, Any], actions: list[Any]) -> Any | None:
    code = str(event.get('action_code') or '').strip()
    if not code:
        return None
    seq = int(event.get('sequence_number') or 0)
    for action in actions:
        action_code = str(getattr(action, 'action_code', '') or '').strip()
        if action_code != code:
            continue
        action_seq = int(getattr(action, 'sequence_number', 0) or 0)
        if seq and action_seq and seq != action_seq:
            continue
        return action
    for action in actions:
        if str(getattr(action, 'action_code', '') or '').strip() == code:
            return action
    return None


def _event_sort_dt(event: dict[str, Any]) -> datetime:
    raw = str(event.get('log_date') or event.get('created_at') or '').strip()
    if not raw:
        return datetime.min
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return datetime.min


def _pick_timeline_event_for_step(
    events: list[dict[str, Any]],
    *,
    step_key: str,
) -> dict[str, Any] | None:
    if not events:
        return None
    reverse = step_key not in _EARLIEST_STEP_KEYS
    ordered = sorted(events, key=_event_sort_dt, reverse=reverse)
    return ordered[0]


def _find_log_for_event(event: dict[str, Any] | None, logs: list[Any]) -> Any | None:
    if event is None:
        return None
    log_id = str(event.get('log_id') or '').strip()
    if not log_id:
        return None
    for row in logs or []:
        row_id = str(getattr(row, 'log_id', None) or getattr(row, 'pk', '') or '')
        if row_id == log_id:
            return row
    return None


def build_history_timeline_events(
    shipment: Any,
    logs: list[Any],
    *,
    booking: Any | None = None,
    request: Any | None = None,
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Performed + pending workflow rows in Job Detail display order."""
    booking = booking if booking is not None else getattr(shipment, 'booking', None)
    tenant_schema = _tenant_schema_from_request(request)
    context = JobDetailContext(
        driver=None,
        tenant_schema=tenant_schema,
        user_id='history',
        job_type='shipment',
        job_id=str(getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', '') or ''),
        shipment=shipment,
        booking=booking,
    )
    service = JobDetailTimelineService()
    actions = service._filter_workflow_actions_for_context(
        service._workflow_actions(),
        context=context,
    )
    if not actions:
        return [], []
    events = merge_actions_with_timeline_logs(
        actions,
        list(logs or []),
        request=request,
        shipment=shipment,
        tenant_schema=tenant_schema,
    )
    return sort_timeline_display_order(filter_hidden_timeline_events(events)), actions


def index_timeline_events_by_step_key(
    events: list[dict[str, Any]],
    actions: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events or []:
        if not event.get('is_performed'):
            continue
        action = _resolve_action_for_event(event, actions)
        step_key = _classify_history_step_key(action)
        if step_key:
            grouped[step_key].append(event)
    return grouped
