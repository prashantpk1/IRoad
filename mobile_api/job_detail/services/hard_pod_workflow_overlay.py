"""
Overlay Job Detail / Execute workflow primary action when hard-copy POD is due.

A7H is hidden from the timeline list but must drive the bottom CTA until custody
is confirmed inside Upload POD.
"""
from __future__ import annotations

from typing import Any


def _hard_copy_due(pod_cod: dict[str, Any] | None) -> bool:
    pod = dict(pod_cod or {})
    if not pod.get('hard_pod_pending') or pod.get('pod_pending'):
        return False
    block = dict(pod.get('hard_copy_confirmation') or {})
    applicable = bool(block.get('applicable') or block.get('required'))
    return applicable and bool(block.get('pending'))


def build_hard_pod_primary_overlay(pod_cod: dict[str, Any] | None) -> dict[str, Any]:
    block = dict((pod_cod or {}).get('hard_copy_confirmation') or {})
    return {
        'action_code': (block.get('execute_action_code') or 'A7H').strip(),
        'action_name': 'Hard POD Collection Confirmation',
        'execution_label': 'Hard POD Collection Confirmation',
        'screen': 'pod_capture',
        'action': 'go_to_pod_capture',
        'capture_mode': 'hard_copy_confirmation',
        'active_step': 'hard_copy_confirmation',
        'ui_mode': 'hard_pod_collection_confirmation',
        'screen_title': 'Hard POD Collection Confirmation',
        'pod_capture_steps': ['digital_evidence', 'hard_copy_confirmation'],
        'capture_step_query': 'hard_copy_confirmation',
        'requires_gps': False,
        'requires_photo': False,
        'requires_video': False,
        'requires_note': False,
    }


def apply_hard_pod_workflow_overlay(
    workflow: dict[str, Any] | None,
    pod_cod: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _hard_copy_due(pod_cod):
        return dict(workflow or {})
    overlay = build_hard_pod_primary_overlay(pod_cod)
    out = dict(workflow or {})
    out['primary_action'] = {**dict(out.get('primary_action') or {}), **overlay}
    out['next_action'] = {**dict(out.get('next_action') or {}), **overlay}
    return out
