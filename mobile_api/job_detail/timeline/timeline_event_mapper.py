"""
mobile_api/job_detail/timeline/timeline_event_mapper.py

Append-only timeline events derived from ``TenantOperationActionLog`` rows.

Action Log is the sole source — no synthetic events from mutable columns alone.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.impacts import operation_action_matches
from mobile_api.helpers.action_navigation_metadata import (
    enrich_timeline_event_navigation,
)
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    TIMELINE_EVENT_ACTION,
    TIMELINE_EVENT_COD,
    TIMELINE_EVENT_DELAY,
    TIMELINE_EVENT_HARD_POD,
    TIMELINE_EVENT_ISSUE,
    TIMELINE_EVENT_MOVEMENT,
    TIMELINE_EVENT_POD,
    classify_timeline_event_type,
)

# Re-export taxonomy constants for existing imports.
EVENT_ACTION = TIMELINE_EVENT_ACTION
EVENT_MOVEMENT = TIMELINE_EVENT_MOVEMENT
EVENT_POD = TIMELINE_EVENT_POD
EVENT_COD = TIMELINE_EVENT_COD
EVENT_HARD_POD = TIMELINE_EVENT_HARD_POD
EVENT_ISSUE = TIMELINE_EVENT_ISSUE
EVENT_DELAY = TIMELINE_EVENT_DELAY

# Operational issue milestone kinds (mobile-staged exceptions, not Action Log).
ISSUE_TIMELINE_OPENED = 'issue_opened'
ISSUE_TIMELINE_ESCALATED = 'issue_escalated'
ISSUE_TIMELINE_RESOLVED = 'issue_resolved'
ISSUE_TIMELINE_REJECTED = 'issue_rejected'


def classify_event_type(action: Any | None) -> str:
    """Delegate to canonical POD action registry (A7≠A8)."""
    return classify_timeline_event_type(action)


def _action_label(log_row: Any, *, request: Any | None = None) -> str:
    action = getattr(log_row, 'operation_action', None)
    if action is None:
        return ''
    english = (
        getattr(action, 'label', '')
        or getattr(action, 'english_label', '')
        or getattr(action, 'action_code', '')
        or ''
    ).strip()
    arabic = (getattr(action, 'arabic_label', '') or '').strip()
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
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Map one Action Log ORM row to a timeline event DTO (append-only derived)."""
    action = getattr(log_row, 'operation_action', None)
    source_channel = str(getattr(log_row, 'source_channel', '') or '').strip()
    log_id = str(getattr(log_row, 'log_id', None) or getattr(log_row, 'pk', '') or '')
    event_type = classify_event_type(action)
    impact = ''
    if action is not None:
        impact = (
            action.shipment_status_impact or action.movement_status_impact or ''
        ).strip()

    log_date = getattr(log_row, 'log_date', None)
    created_at = getattr(log_row, 'created_at', None)

    event = {
        'log_id': log_id,
        'log_no': str(getattr(log_row, 'log_no', '') or ''),
        'log_date': log_date.isoformat() if hasattr(log_date, 'isoformat') else '',
        'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else '',
        'event_type': event_type,
        'action_code': (
            'A_POD_VERIFY'
            if source_channel == 'auto_cod_verify'
            else str(getattr(action, 'action_code', '') or '')
        ),
        'action_label': _action_label(log_row, request=request),
        'is_system_auto': source_channel == 'auto_cod_verify',
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
    return enrich_timeline_event_navigation(
        event,
        action,
        shipment=shipment,
        tenant_schema=tenant_schema,
    )


def map_logs_to_timeline_events(
    logs: list[Any],
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> list[dict[str, Any]]:
    """Map log rows preserving input order (caller must supply stable sort)."""
    return [
        map_log_to_timeline_event(
            row,
            request=request,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )
        for row in logs
    ]


def map_action_to_pending_timeline_event(
    action: Any,
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Map one configured workflow action to an unperformed timeline step."""
    event_type = classify_event_type(action)
    impact = ''
    if action is not None:
        impact = (
            getattr(action, 'shipment_status_impact', '')
            or getattr(action, 'movement_status_impact', '')
            or ''
        ).strip()

    event = {
        'log_id': '',
        'log_no': '',
        'log_date': '',
        'created_at': '',
        'event_type': event_type,
        'action_code': str(getattr(action, 'action_code', '') or ''),
        'action_label': _action_label_from_action(action, request=request),
        'source': '',
        'source_channel': '',
        'notes': '',
        'status_impact': impact or None,
        'shipment_id': None,
        'movement_id': None,
        'latitude': '',
        'longitude': '',
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
        'append_only': False,
        'authority': 'action_master',
        'timeline_state': 'pending',
        'is_performed': False,
        'sequence_number': int(getattr(action, 'sequence_number', 0) or 0),
    }
    return enrich_timeline_event_navigation(
        event,
        action,
        shipment=shipment,
        tenant_schema=tenant_schema,
    )


def merge_actions_with_timeline_logs(
    actions: list[Any],
    logs: list[Any],
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> list[dict[str, Any]]:
    """
    Build a workflow progression timeline.

    Every configured action appears once in sequence order. If a matching
    Action Log exists, its details fill the row; otherwise the row is pending.
    """
    latest_log_by_action_id: dict[str, Any] = {}
    for log in sort_logs_newest_first(list(logs)):
        action = getattr(log, 'operation_action', None)
        action_id = str(getattr(action, 'action_id', '') or '')
        if action_id and action_id not in latest_log_by_action_id:
            latest_log_by_action_id[action_id] = log

    out: list[dict[str, Any]] = []
    for action in sorted(
        actions,
        key=lambda row: (
            int(getattr(row, 'sequence_number', 0) or 0),
            str(getattr(row, 'action_code', '') or ''),
        ),
    ):
        action_id = str(getattr(action, 'action_id', '') or '')
        log = latest_log_by_action_id.get(action_id)
        if log is None:
            out.append(
                map_action_to_pending_timeline_event(
                    action,
                    request=request,
                    shipment=shipment,
                    tenant_schema=tenant_schema,
                ),
            )
            continue
        event = map_log_to_timeline_event(
            log,
            request=request,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )
        event['timeline_state'] = 'performed'
        event['is_performed'] = True
        event['sequence_number'] = int(getattr(action, 'sequence_number', 0) or 0)
        out.append(event)
    return out


def _action_label_from_action(action: Any, *, request: Any | None = None) -> str:
    if action is None:
        return ''
    english = (
        getattr(action, 'label', '')
        or getattr(action, 'english_label', '')
        or getattr(action, 'action_code', '')
        or ''
    ).strip()
    arabic = (getattr(action, 'arabic_label', '') or '').strip()
    if request is not None:
        try:
            from mobile_api.helpers.i18n import get_localized_value

            return get_localized_value(request, english, arabic) or english
        except Exception:
            pass
    return english


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


def classify_issue_escalation_milestone(
    *,
    to_state: str,
    event_type: str = '',
) -> str:
    """Map escalation row to opened / escalated / resolved timeline kind."""
    state = (to_state or '').strip().casefold()
    if state == 'resolved':
        return ISSUE_TIMELINE_RESOLVED
    if state == 'rejected':
        return ISSUE_TIMELINE_REJECTED
    if state == 'escalated' or (event_type or '').strip() == 'auto_escalated':
        return ISSUE_TIMELINE_ESCALATED
    if state in {'open', 'acknowledged'} or (event_type or '').strip() == 'issue_reported':
        return ISSUE_TIMELINE_OPENED
    return ISSUE_TIMELINE_OPENED


def map_escalation_event_to_timeline(
    event: Any,
    *,
    issue: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Map one ``OperationalIssueEscalationEvent`` to a timeline DTO."""
    _ = request
    issue_row = issue or getattr(event, 'issue', None)
    issue_type = (getattr(issue_row, 'issue_type', None) or '').strip()
    milestone = classify_issue_escalation_milestone(
        to_state=str(getattr(event, 'to_state', '') or ''),
        event_type=str(getattr(event, 'event_type', '') or ''),
    )
    recorded_at = getattr(event, 'recorded_at', None)
    ts = recorded_at.isoformat() if hasattr(recorded_at, 'isoformat') else ''

    label = issue_type.replace('_', ' ').title() if issue_type else 'Issue'
    if milestone == ISSUE_TIMELINE_ESCALATED:
        action_label = f'{label} escalated'
    elif milestone == ISSUE_TIMELINE_RESOLVED:
        action_label = f'{label} resolved'
    elif milestone == ISSUE_TIMELINE_REJECTED:
        action_label = f'{label} rejected'
    else:
        action_label = f'{label} opened'

    return {
        'event_id': str(getattr(event, 'pk', '') or getattr(event, 'id', '') or ''),
        'log_id': '',
        'log_no': '',
        'log_date': ts,
        'created_at': ts,
        'event_type': EVENT_ISSUE,
        'issue_timeline_kind': milestone,
        'action_code': '',
        'action_label': action_label,
        'source': 'Mobile',
        'source_channel': 'operational_issue',
        'notes': str(getattr(event, 'notes', '') or ''),
        'status_impact': None,
        'shipment_id': str(getattr(event, 'shipment_id', '') or '') or None,
        'movement_id': None,
        'latitude': '',
        'longitude': '',
        'is_reversal': False,
        'append_only': True,
        'authority': 'operational_issue',
        'issue_id': str(getattr(issue_row, 'pk', '') or '') if issue_row else '',
        'escalation_state': str(getattr(event, 'to_state', '') or ''),
        'severity': str(getattr(issue_row, 'severity', '') or '') if issue_row else '',
    }


def map_escalation_events_to_timeline(
    events: list[Any],
    *,
    issues_by_id: dict[str, Any] | None = None,
    request: Any | None = None,
) -> list[dict[str, Any]]:
    issues_by_id = issues_by_id or {}
    out: list[dict[str, Any]] = []
    for event in events:
        issue_id = str(getattr(event, 'issue_id', '') or '')
        issue = issues_by_id.get(issue_id)
        out.append(
            map_escalation_event_to_timeline(event, issue=issue, request=request),
        )
    return out


def merge_issue_events_into_timeline(
    action_log_events: list[dict[str, Any]],
    issue_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Merge operational issue milestones into Action Log timeline (newest first).

    Issue events use ``event_id``; Action Log events use ``log_id`` — no collision.
    """
    combined = list(action_log_events or []) + list(issue_events or [])

    def _sort_key(row: dict[str, Any]) -> tuple:
        return (
            str(row.get('created_at') or row.get('log_date') or ''),
            str(row.get('event_id') or row.get('log_id') or ''),
        )

    combined.sort(key=_sort_key, reverse=True)

    seen_issue: set[str] = set()
    seen_log: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in combined:
        log_id = str(row.get('log_id') or '').strip()
        event_id = str(row.get('event_id') or '').strip()
        if log_id:
            if log_id in seen_log:
                continue
            seen_log.add(log_id)
        elif event_id:
            if event_id in seen_issue:
                continue
            seen_issue.add(event_id)
        out.append(row)
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
