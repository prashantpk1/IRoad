"""
mobile_api/pod_capture/policy/compliance_log_evidence.py

Action-log evidence flags using :mod:`canonical_pod_action_registry`.

Replaces ad-hoc reconciler needle lists (fixes A7/A8/delivered confusion).
"""
from __future__ import annotations

from typing import Any

from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    PodActionRole,
    action_has_role,
    classify_pod_action_role,
)


def log_evidence_flags(logs: list[Any]) -> dict[str, bool]:
    """Derive compliance signals from append-only Action Log rows."""
    flags = {
        'pod_uploaded': False,
        'cod_collected_log': False,
        'delivered_log': False,
        'hard_pod_log': False,
    }

    for log in logs:
        action = getattr(log, 'operation_action', None)
        if action is None:
            continue
        code = (getattr(action, 'action_code', '') or '').strip().upper()
        channel = (getattr(log, 'source_channel', '') or '').strip()
        if code == 'A_POD_VERIFY' or channel == 'auto_cod_verify':
            flags['delivered_log'] = True
        role = classify_pod_action_role(action)
        if role == PodActionRole.POD_UPLOAD:
            flags['pod_uploaded'] = True
        elif role == PodActionRole.COD_COLLECT:
            flags['cod_collected_log'] = True
        elif role == PodActionRole.DELIVERED_STATUS:
            flags['delivered_log'] = True
        elif role == PodActionRole.HARD_POD:
            flags['hard_pod_log'] = True

    return flags


def action_log_matches_pod_upload(log_row: Any) -> bool:
    action = getattr(log_row, 'operation_action', None)
    return action_has_role(action, PodActionRole.POD_UPLOAD)


def action_log_matches_delivered(log_row: Any) -> bool:
    action = getattr(log_row, 'operation_action', None)
    return action_has_role(action, PodActionRole.DELIVERED_STATUS)
