"""
mobile_api/job_detail/timeline/timeline_event_mapper.py

Append-only timeline events derived from ``TenantOperationActionLog`` rows.

Action Log is the sole source — no synthetic events from mutable columns alone.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.impacts import operation_action_matches

# Event taxonomy for mobile Job Detail timeline UI.
EVENT_ACTION = 'action'
EVENT_MOVEMENT = 'movement'
EVENT_POD = 'pod'
EVENT_COD = 'cod'
EVENT_HARD_POD = 'hard_pod'
EVENT_ISSUE = 'issue'
EVENT_DELAY = 'delay'


def classify_event_type(action: Any | None) -> str:
    """
    Classify one Action Master row into a timeline event category.

    Order matters: compliance/delay/issue before generic movement/action.
    """
    if action is None:
        return EVENT_ACTION

    if operation_action_matches(
        action,
        'delay',
        'delayed',
        'late arrival',
        'traffic delay',
        'waiting',
    ):
        return EVENT_DELAY

    if operation_action_matches(
        action,
        'issue',
        'incident',
        'problem',
        'breakdown',
        'accident',
        'complaint',
    ):
        return EVENT_ISSUE

    if getattr(action, 'hard_copy_collection', False) or operation_action_matches(
        action,
        'hard pod',
        'hard copy',
        'hard-copy',
        'delivery note',
    ):
        return EVENT_HARD_POD

    if operation_action_matches(
        action,
        'collect payment',
        'cod',
        'cash on delivery',
        'a9',
        'action 9',
        'payment collection',
    ):
        return EVENT_COD

    if getattr(action, 'auto_pod_post', False) or operation_action_matches(
        action,
        'pod',
        'upload pod',
        'submit pod',
        'a7',
        'action 7',
        'a8',
        'action 8',
        'proof of delivery',
    ):
        return EVENT_POD

    if (action.movement_status_impact or '').strip() or operation_action_matches(
        action,
        'movement',
        'empty move',
        'depart yard',
        'arrive',
        'start move',
    ):
        return EVENT_MOVEMENT

    return EVENT_ACTION


def _action_label(log_row: Any, *, request: Any | None = None) -> str:
    action = getattr(log_row, 'operation_action', None)
    if action is None:
        return ''
    english = (action.english_label or action.action_code or '').strip()
    arabic = (action.arabic_label or '').strip()
    if request is not None:
        try:
            from mobile_api.helpers.i18n import get_localized_value

            return get_localized_value(request, english, arabic) or english
        except Exception:
            pass
    return english


def map_log_to_timeline_event(
    log_row: Any,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """Map one Action Log ORM row to a timeline event DTO (append-only derived)."""
    action = getattr(log_row, 'operation_action', None)
    log_id = str(getattr(log_row, 'log_id', None) or getattr(log_row, 'pk', '') or '')
    event_type = classify_event_type(action)
    impact = ''
    if action is not None:
        impact = (
            action.shipment_status_impact or action.movement_status_impact or ''
        ).strip()

    log_date = getattr(log_row, 'log_date', None)
    created_at = getattr(log_row, 'created_at', None)

    return {
        'log_id': log_id,
        'log_no': str(getattr(log_row, 'log_no', '') or ''),
        'log_date': log_date.isoformat() if hasattr(log_date, 'isoformat') else '',
        'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else '',
        'event_type': event_type,
        'action_code': str(getattr(action, 'action_code', '') or ''),
        'action_label': _action_label(log_row, request=request),
        'source': str(getattr(log_row, 'source', '') or ''),
        'source_channel': str(getattr(log_row, 'source_channel', '') or ''),
        'notes': str(getattr(log_row, 'notes', '') or ''),
        'status_impact': impact or None,
        'shipment_id': str(getattr(log_row, 'shipment_id', None) or '') or None,
        'movement_id': str(getattr(log_row, 'truck_movement_id', None) or '') or None,
        'latitude': str(getattr(log_row, 'latitude', '') or ''),
        'longitude': str(getattr(log_row, 'longitude', '') or ''),
        'is_reversal': operation_action_matches(
            action,
            'reversal',
            'reject pod',
            'reject',
            'cancel shipment',
            'undo',
        )
        if action
        else False,
        'append_only': True,
        'authority': 'action_log',
    }


def map_logs_to_timeline_events(
    logs: list[Any],
    *,
    request: Any | None = None,
) -> list[dict[str, Any]]:
    """Map log rows preserving input order (caller must supply stable sort)."""
    return [map_log_to_timeline_event(row, request=request) for row in logs]


def dedupe_timeline_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Remove duplicate ``log_id`` entries while preserving first occurrence order.

    Defensive guard for merged shipment direct + movement-linked sources.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for event in events:
        log_id = str(event.get('log_id') or '').strip()
        if not log_id or log_id in seen:
            continue
        seen.add(log_id)
        out.append(event)
    return out


def sort_logs_newest_first(logs: list[Any]) -> list[Any]:
    """Stable sort matching ``TIMELINE_ORDER`` (-log_date, -created_at, -log_id)."""

    def _key(row: Any) -> tuple:
        log_date = getattr(row, 'log_date', None)
        created_at = getattr(row, 'created_at', None)
        log_id = str(getattr(row, 'log_id', None) or getattr(row, 'pk', '') or '')
        return (
            log_date.isoformat() if hasattr(log_date, 'isoformat') else '',
            created_at.isoformat() if hasattr(created_at, 'isoformat') else '',
            log_id,
        )

    return sorted(logs, key=_key, reverse=True)
