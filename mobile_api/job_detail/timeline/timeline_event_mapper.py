"""
mobile_api/job_detail/timeline/timeline_event_mapper.py

Append-only timeline events derived from ``TenantOperationActionLog`` rows.

Action Log is the sole source — no synthetic events from mutable columns alone.
"""
from __future__ import annotations

from typing import Any

from iroad_tenants.operation_runtime.impacts import (
    operation_action_matches,
    resolve_shipment_status_impact,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    is_delivery_arrival_action,
    is_departure_action,
    is_loading_action,
    is_pickup_action,
    is_pickup_or_loading_action,
    is_unloading_action,
    is_unloading_completed_action,
)
from iroad_tenants.operation_runtime.workflow_action_policy import (
    normalize_workflow_action_label,
)
from mobile_api.helpers.action_execution_metadata import _is_start_job_action
from mobile_api.helpers.action_navigation_metadata import (
    build_hard_copy_navigation_payload,
    enrich_timeline_event_navigation,
)
from mobile_api.helpers.job_action_resolver import (
    action_code_is_job_close,
    row_is_job_close_action,
)
from mobile_api.dashboard.services.dashboard_pod_cod_reconciler import (
    _log_evidence_flags,
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
    is_pod_upload_action,
    is_unloading_action,
)
from iroad_tenants.operation_runtime.action_master_catalog import (
    AUTO_COD_VERIFY_ACTION_CODE,
    AUTO_COD_VERIFY_ARABIC_LABEL,
    AUTO_COD_VERIFY_ENGLISH_LABEL,
    SYSTEM_AUTO_POD_VERIFY_CHANNELS,
    is_system_auto_pod_verify_channel,
)
from tenant_workspace.models import TenantShipment

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

SYSTEM_AUTO_TIMELINE_CODES = frozenset({AUTO_COD_VERIFY_ACTION_CODE})
SYSTEM_AUTO_TIMELINE_CHANNELS = SYSTEM_AUTO_POD_VERIFY_CHANNELS


def _system_auto_pod_verify_label(*, request: Any | None = None) -> str:
    if request is not None:
        try:
            from mobile_api.helpers.i18n import get_localized_value

            return (
                get_localized_value(
                    request,
                    AUTO_COD_VERIFY_ENGLISH_LABEL,
                    AUTO_COD_VERIFY_ARABIC_LABEL,
                )
                or AUTO_COD_VERIFY_ENGLISH_LABEL
            )
        except Exception:
            pass
    return AUTO_COD_VERIFY_ENGLISH_LABEL


def timeline_event_is_pod_verified(event: dict[str, Any]) -> bool:
    """System auto-verify milestone — hidden from driver timeline UI."""
    code = str(event.get('action_code') or '').strip().upper()
    if code in SYSTEM_AUTO_TIMELINE_CODES:
        return True
    channel = str(event.get('source_channel') or '').strip()
    if channel in SYSTEM_AUTO_TIMELINE_CHANNELS:
        return True
    label = str(
        event.get('action_label')
        or event.get('execution_label')
        or event.get('label')
        or '',
    ).casefold()
    return 'pod verified' in label or 'pod verify' in label


def filter_hidden_timeline_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove internal milestones that must not appear in the mobile stepper."""
    return [row for row in (events or []) if not timeline_event_is_pod_verified(row)]


def classify_event_type(action: Any | None) -> str:
    """Delegate to canonical POD action registry (A7≠A8)."""
    return classify_timeline_event_type(action)


def _string_field(obj: Any, *attrs: str) -> str:
    for attr in attrs:
        value = getattr(obj, attr, '')
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _action_master_label(action: Any) -> str:
    """Prefer Action Master ``english_label`` (tenant codes are dynamic)."""
    return _string_field(action, 'english_label', 'label', 'action_code')


def _action_label(log_row: Any, *, request: Any | None = None) -> str:
    action = getattr(log_row, 'operation_action', None)
    if action is None:
        return ''
    english = _action_master_label(action)
    arabic = _string_field(action, 'arabic_label')
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
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Map one Action Log ORM row to a timeline event DTO (append-only derived)."""
    action = getattr(log_row, 'operation_action', None)
    source_channel = str(getattr(log_row, 'source_channel', '') or '').strip()
    is_system_auto = is_system_auto_pod_verify_channel(source_channel)
    log_id = str(getattr(log_row, 'log_id', None) or getattr(log_row, 'pk', '') or '')
    event_type = classify_event_type(action)
    impact = ''
    if is_system_auto:
        impact = TenantShipment.ShipmentStatus.DELIVERED
    elif action is not None:
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
            AUTO_COD_VERIFY_ACTION_CODE
            if is_system_auto
            else str(getattr(action, 'action_code', '') or '')
        ),
        'action_label': (
            _system_auto_pod_verify_label(request=request)
            if is_system_auto
            else _action_label(log_row, request=request)
        ),
        'is_system_auto': is_system_auto,
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
        log_evidence=log_evidence,
    )


def map_logs_to_timeline_events(
    logs: list[Any],
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Map log rows preserving input order (caller must supply stable sort)."""
    evidence = dict(log_evidence or _log_evidence_flags(logs))
    return [
        map_log_to_timeline_event(
            row,
            request=request,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=evidence,
        )
        for row in logs
    ]


def map_action_to_pending_timeline_event(
    action: Any,
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
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

    action_code = str(getattr(action, 'action_code', '') or '')
    event = {
        'log_id': '',
        'log_no': '',
        'log_date': '',
        'created_at': '',
        'event_type': event_type,
        'action_code': action_code,
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
    event = enrich_timeline_event_navigation(
        event,
        action,
        shipment=shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
    return event


def _action_bool_is_true(action: Any, field: str) -> bool:
    return getattr(action, field, None) is True


def _is_loading_completed_milestone(action: Any) -> bool:
    """Strict loading-completed milestone (ignores truthy ORM/MagicMock placeholders)."""
    if action is None:
        return False
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        is_confirm_loaded_action,
    )

    if is_confirm_loaded_action(action):
        return False
    label = (getattr(action, 'english_label', '') or '').casefold()
    if 'loading completed' in label or 'load complete' in label:
        return True
    if _action_bool_is_true(action, 'auto_shipment_post'):
        return True
    return operation_action_matches(action, 'loading completed')


def _workflow_milestone_key(action: Any) -> str | None:
    """Exclusive milestone bucket for one workflow step / log action."""
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    if action is None:
        return None
    if is_pickup_action(action):
        return 'pickup'
    if is_loading_action(action):
        return 'loading'
    if _is_loading_completed_milestone(action):
        return 'loading_completed'
    if is_departure_action(action):
        return 'departure'
    if is_delivery_arrival_action(action):
        return 'delivery_arrival'
    if is_unloading_action(action):
        return 'unloading'
    if is_unloading_completed_action(action):
        return 'unloading_completed'
    if is_pod_upload_action(action):
        return 'pod_upload'
    return None


def _semantic_log_matchers_for_workflow_action(action: Any) -> tuple[Any, ...]:
    """Return log-side predicates that satisfy this workflow step."""
    milestone = _workflow_milestone_key(action)
    if not milestone:
        return ()

    def _matches(logged_action: Any) -> bool:
        return _workflow_milestone_key(logged_action) == milestone

    return (_matches,)


def _find_semantic_log_for_workflow_action(
    action: Any,
    logs: list[Any],
    *,
    used_log_ids: set[str] | None = None,
) -> Any | None:
    """
    Match a workflow row to a log by milestone semantics when id/code/label differ.

    Ensures Departure turns green on its own log — not only after Delivery Arrival.
    """
    matchers = _semantic_log_matchers_for_workflow_action(action)
    if not matchers:
        return None
    consumed = used_log_ids or set()
    for log in sort_logs_newest_first(list(logs)):
        log_id = str(getattr(log, 'log_id', None) or getattr(log, 'pk', '') or '').strip()
        if log_id and log_id in consumed:
            continue
        logged_action = getattr(log, 'operation_action', None)
        if logged_action is None:
            continue
        if any(matcher(logged_action) for matcher in matchers):
            return log
    return None


def _timeline_row_is_collect_payment(event: dict[str, Any]) -> bool:
    from mobile_api.helpers.job_action_resolver import row_is_collect_payment_action

    return row_is_collect_payment_action(event)


def reconcile_hard_pod_timeline_events(
    events: list[dict[str, Any]],
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """
    Hard-copy custody is step 2 inside Upload POD — not a separate timeline row.

    Keep a single performed POD milestone on the timeline. Job Detail workflow
    overlay + ``next_action_hint`` drive the hard-copy wizard after digital POD.
    """
    _ = shipment
    _ = tenant_schema
    _ = log_evidence
    return list(events or [])


def merge_actions_with_timeline_logs(
    actions: list[Any],
    logs: list[Any],
    *,
    request: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """
    Build a workflow progression timeline.

    Every configured action appears once in sequence order. If a matching
    Action Log exists, its details fill the row; otherwise the row is pending.
    """
    latest_log_by_action_id: dict[str, Any] = {}
    latest_log_by_action_code: dict[str, Any] = {}
    latest_log_by_action_label: dict[str, Any] = {}
    for log in sort_logs_newest_first(list(logs)):
        action = getattr(log, 'operation_action', None)
        action_id = str(getattr(action, 'action_id', '') or '')
        if action_id and action_id not in latest_log_by_action_id:
            latest_log_by_action_id[action_id] = log
        code = str(getattr(action, 'action_code', '') or '').strip().casefold()
        if code and code not in latest_log_by_action_code:
            latest_log_by_action_code[code] = log
        label = normalize_workflow_action_label(action)
        if label and label not in latest_log_by_action_label:
            latest_log_by_action_label[label] = log

    evidence = dict(log_evidence or _log_evidence_flags(logs))
    used_log_ids: set[str] = set()
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
            code = str(getattr(action, 'action_code', '') or '').strip().casefold()
            if code:
                log = latest_log_by_action_code.get(code)
        if log is None:
            label = normalize_workflow_action_label(action)
            if label:
                log = latest_log_by_action_label.get(label)
        if log is None:
            log = _find_semantic_log_for_workflow_action(
                action,
                logs,
                used_log_ids=used_log_ids,
            )
        if log is None:
            out.append(
                map_action_to_pending_timeline_event(
                    action,
                    request=request,
                    shipment=shipment,
                    tenant_schema=tenant_schema,
                    log_evidence=evidence,
                ),
            )
            continue
        event = map_log_to_timeline_event(
            log,
            request=request,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=evidence,
        )
        event['timeline_state'] = 'performed'
        event['is_performed'] = True
        event['sequence_number'] = int(getattr(action, 'sequence_number', 0) or 0)
        event['action_code'] = str(getattr(action, 'action_code', '') or '')
        event['action_label'] = _action_label_from_action(action, request=request)
        if str(getattr(log, 'source_channel', '') or '').strip() in SYSTEM_AUTO_TIMELINE_CHANNELS:
            event['is_system_auto'] = True
            event['sequence_number'] = max(int(event.get('sequence_number') or 0), 999)
        log_id = str(getattr(log, 'log_id', None) or getattr(log, 'pk', '') or '').strip()
        if log_id:
            used_log_ids.add(log_id)
        out.append(event)
    out = reconcile_hard_pod_timeline_events(
        out,
        shipment=shipment,
        tenant_schema=tenant_schema,
        log_evidence=evidence,
    )
    return _reconcile_out_of_order_pod_events(out, actions=actions, logs=logs)


def _resolve_workflow_action_for_event(
    event: dict[str, Any],
    actions: list[Any] | None,
) -> Any | None:
    """Match a timeline row to its Action Master row (code + sequence)."""
    if not actions:
        return None
    code = (event.get('action_code') or '').strip()
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
    return None


def _is_delivery_arrival_action(action: Any | None) -> bool:
    if action is None:
        return False
    impact = resolve_shipment_status_impact(
        (getattr(action, 'shipment_status_impact', None) or '').strip(),
    )
    if impact == TenantShipment.ShipmentStatus.AT_DELIVERY:
        return True
    return operation_action_matches(action, 'delivery arrival', 'arrival at delivery')


def _is_delivery_arrival_event(
    event: dict[str, Any],
    *,
    actions: list[Any] | None = None,
) -> bool:
    action = _resolve_workflow_action_for_event(event, actions)
    if action is not None and _is_delivery_arrival_action(action):
        return True
    label = (event.get('action_label') or '').casefold()
    return 'delivery' in label and 'arrival' in label


def _is_start_unloading_event(
    event: dict[str, Any],
    *,
    actions: list[Any] | None = None,
) -> bool:
    action = _resolve_workflow_action_for_event(event, actions)
    if action is not None and is_unloading_action(action):
        return True
    label = (event.get('action_label') or '').casefold()
    return 'start unloading' in label


def _is_pod_upload_event(
    event: dict[str, Any],
    *,
    actions: list[Any] | None = None,
) -> bool:
    action = _resolve_workflow_action_for_event(event, actions)
    if action is not None and is_pod_upload_action(action):
        return True
    return (event.get('event_type') or '').strip().casefold() in {
        'pod',
        'hard_pod',
    }


def _pod_logs_follow_delivery_prerequisites(
    logs: list[Any],
) -> bool:
    """POD log must exist after delivery arrival and start unloading logs."""
    pod_ts = None
    delivery_ts = None
    unloading_ts = None
    for log in logs or []:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        ts = getattr(log, 'log_date', None) or getattr(log, 'created_at', None)
        if ts is None:
            continue
        if is_pod_upload_action(action):
            pod_ts = ts if pod_ts is None or ts > pod_ts else pod_ts
        if is_delivery_arrival_action(action):
            delivery_ts = ts if delivery_ts is None or ts > delivery_ts else delivery_ts
        if is_unloading_action(action):
            unloading_ts = ts if unloading_ts is None or ts > unloading_ts else unloading_ts
    if pod_ts is None:
        return True
    if delivery_ts is None or unloading_ts is None:
        return False
    return pod_ts >= delivery_ts and pod_ts >= unloading_ts


def _reconcile_out_of_order_pod_events(
    events: list[dict[str, Any]],
    *,
    actions: list[Any] | None = None,
    logs: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """
    POD must not appear complete when delivery arrival or unloading were skipped.

    Hides out-of-order POD logs from the workflow progression view so drivers
    see the correct next mandatory steps (delivery → unloading → POD).
    """
    if logs is not None and _pod_logs_follow_delivery_prerequisites(logs):
        return events

    delivery_done = any(
        event.get('is_performed') and _is_delivery_arrival_event(event, actions=actions)
        for event in events
    )
    unloading_done = any(
        event.get('is_performed') and _is_start_unloading_event(event, actions=actions)
        for event in events
    )
    if delivery_done and unloading_done and logs is None:
        return events

    reconciled: list[dict[str, Any]] = []
    for event in events:
        if event.get('is_performed') and _is_pod_upload_event(event, actions=actions):
            pending = dict(event)
            pending['is_performed'] = False
            pending['timeline_state'] = 'pending'
            pending['prerequisite_violation'] = True
            reconciled.append(pending)
            continue
        reconciled.append(event)
    return reconciled


def _allows_implicit_forward_cascade(
    event: dict[str, Any],
    *,
    actions: list[Any] | None = None,
) -> bool:
    """Only optional steps (e.g. Start Unloading) may be implied by a later log."""
    action = _resolve_workflow_action_for_event(event, actions)
    if action is not None:
        if is_pickup_or_loading_action(action):
            return False
        if _is_start_job_action(action):
            return False
        if is_departure_action(action):
            return False
        if is_delivery_arrival_action(action):
            return False
    return _is_start_unloading_event(event, actions=actions)


def _apply_forward_step_cascade(
    events: list[dict[str, Any]],
    *,
    actions: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Mark earlier optional workflow steps performed when a later step was executed.

    Pickup Arrival and Start Loading always require their own action log.
    """
    max_performed_seq = max(
        (
            int(event.get('sequence_number') or 0)
            for event in events
            if event.get('is_performed')
        ),
        default=0,
    )
    if max_performed_seq <= 0:
        return events

    cascaded: list[dict[str, Any]] = []
    for event in events:
        if event.get('is_performed'):
            cascaded.append(event)
            continue
        seq = int(event.get('sequence_number') or 0)
        if seq > 0 and seq < max_performed_seq and _allows_implicit_forward_cascade(
            event,
            actions=actions,
        ):
            implied = dict(event)
            implied['is_performed'] = True
            implied['timeline_state'] = 'performed'
            implied['implicit_performed'] = True
            implied['authority'] = 'workflow_cascade'
            cascaded.append(implied)
            continue
        cascaded.append(event)
    return cascaded


def _action_label_from_action(action: Any, *, request: Any | None = None) -> str:
    if action is None:
        return ''
    english = _action_master_label(action)
    arabic = _string_field(action, 'arabic_label')
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


def _timeline_event_is_job_close(event: dict[str, Any]) -> bool:
    row = {
        'action_code': event.get('action_code'),
        'english_label': event.get('action_label'),
        'execution_label': event.get('execution_label'),
        'label': event.get('label'),
        'execution_requirements': {
            'shipment_status_impact': event.get('status_impact') or '',
        },
    }
    if row_is_job_close_action(row):
        return True
    impact = resolve_shipment_status_impact(str(event.get('status_impact') or ''))
    if impact == TenantShipment.ShipmentStatus.CLOSED:
        return True
    if action_code_is_job_close(str(event.get('action_code') or '')):
        return True
    for label_key in ('action_label', 'execution_label', 'label'):
        label = str(event.get(label_key) or '').casefold()
        if (
            'job close' in label
            or 'job closed' in label
            or 'close job' in label
        ):
            return True
    return False


def _timeline_event_is_system_auto(event: dict[str, Any]) -> bool:
    if event.get('is_system_auto'):
        return True
    code = str(event.get('action_code') or '').strip().upper()
    if code in SYSTEM_AUTO_TIMELINE_CODES:
        return True
    if str(event.get('source_channel') or '').strip() in SYSTEM_AUTO_TIMELINE_CHANNELS:
        return True
    label = str(event.get('action_label') or event.get('execution_label') or '').casefold()
    return 'pod verified' in label or 'pod verify' in label


def sort_timeline_display_order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Display order for mobile stepper:

    workflow steps (1..N) → Job Closed last.

    ``POD Verified`` is a system-only milestone and is filtered out before sort.
    """
    events = filter_hidden_timeline_events(events)
    if not events:
        return events

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, str, str]:
        if _timeline_event_is_job_close(row):
            tier = 2
        elif _timeline_event_is_system_auto(row):
            tier = 1
        else:
            tier = 0
        seq = int(row.get('sequence_number') or 0)
        log_date = str(row.get('log_date') or row.get('created_at') or '')
        log_id = str(row.get('log_id') or row.get('event_id') or '')
        return (tier, seq, log_date, log_id)

    return sorted(events, key=_sort_key)


def pin_job_close_timeline_last(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible alias for timeline display ordering."""
    return sort_timeline_display_order(events)


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
