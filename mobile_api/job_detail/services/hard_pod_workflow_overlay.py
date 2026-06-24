"""
Overlay Job Detail / Execute workflow primary action when hard-copy POD is due.

A7H is hidden from the timeline list but must drive the bottom CTA until custody
is confirmed inside Upload POD.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.job_action_resolver import (
    row_is_collect_payment_action,
    row_is_job_close_action,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
)
from mobile_api.pod_capture.services.pod_section_metadata import build_pod_capture_steps

HARD_COPY_GATE_REASON = (
    'Digital POD is uploaded. Confirm hard-copy delivery note pages '
    'inside Upload POD before collecting payment.'
)


def _hard_copy_due(pod_cod: dict[str, Any] | None) -> bool:
    pod = dict(pod_cod or {})
    if not pod.get('hard_pod_pending') or pod.get('pod_pending'):
        return False
    block = dict(pod.get('hard_copy_confirmation') or {})
    return bool(block.get('applicable') or block.get('required'))


def build_hard_pod_primary_overlay(pod_cod: dict[str, Any] | None) -> dict[str, Any]:
    block = dict((pod_cod or {}).get('hard_copy_confirmation') or {})
    return {
        'action_code': (
            block.get('execute_action_code') or CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE
        ).strip(),
        'action_name': 'Hard POD Collection Confirmation',
        'execution_label': 'Hard POD Collection Confirmation',
        'screen': 'pod_capture',
        'action': 'go_to_pod_capture',
        'capture_mode': 'hard_copy_confirmation',
        'active_step': 'hard_copy_confirmation',
        'ui_mode': 'hard_pod_collection_confirmation',
        'screen_title': 'Hard POD Collection Confirmation',
        'pod_capture_steps': build_pod_capture_steps(hard_pod=True),
        'hard_pod': True,
        'capture_step_query': 'hard_copy_confirmation',
        'requires_gps': False,
        'requires_photo': False,
        'requires_video': False,
        'requires_note': False,
    }


def _gate_allowed_actions_while_hard_copy_due(
    allowed_actions: list[Any] | None,
    overlay: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Hide Collect Payment / Job Close until hard-copy custody completes.

    Hard copy is step 2 inside Upload POD — drivers must not see payment as the
    primary forward action while ``hard_pod_pending`` is true.
    """
    gated: list[dict[str, Any]] = []
    for row in allowed_actions or []:
        if not isinstance(row, dict):
            continue
        if row_is_collect_payment_action(row) or row_is_job_close_action(row):
            continue
        gated.append(dict(row))
    if not gated:
        return [dict(overlay)]
    return gated


def finalize_pod_cod_hard_copy_navigation(
    pod_cod: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Remove active hard-copy wizard contracts once custody is complete.

    Mobile must not open Upload POD step 2 from stale ``confirmation_ui`` on
    closed or post-custody jobs.
    """
    pod = dict(pod_cod or {})
    if pod.get('hard_pod_pending'):
        return pod
    block = dict(pod.get('hard_copy_confirmation') or {})
    if not block:
        pod['payment_collection_blocked'] = False
        pod.pop('payment_collection_block_reason', None)
        return pod
    block['pending'] = False
    block['submit_allowed'] = False
    block['actionable'] = False
    block.pop('confirmation_ui', None)
    block['ui_mode'] = ''
    block['screen_title'] = ''
    pod['hard_copy_confirmation'] = block
    pod['payment_collection_blocked'] = False
    pod.pop('payment_collection_block_reason', None)
    return pod


def enrich_pod_cod_hard_copy_gate(pod_cod: dict[str, Any] | None) -> dict[str, Any]:
    """Expose payment block flags while hard-copy custody is outstanding."""
    pod = dict(pod_cod or {})
    if not _hard_copy_due(pod):
        return finalize_pod_cod_hard_copy_navigation(pod)
    pod['payment_collection_blocked'] = True
    pod['payment_collection_block_reason'] = HARD_COPY_GATE_REASON
    pod['digital_pod_complete'] = not bool(pod.get('pod_pending'))
    return pod


def apply_hard_pod_workflow_overlay(
    workflow: dict[str, Any] | None,
    pod_cod: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _hard_copy_due(pod_cod):
        return dict(workflow or {})
    overlay = build_hard_pod_primary_overlay(pod_cod)
    out = dict(workflow or {})
    # Replace CTA entirely — do not merge Collect Payment labels with hard-copy navigation.
    out['primary_action'] = dict(overlay)
    out['next_action'] = dict(overlay)
    out['allowed_actions'] = _gate_allowed_actions_while_hard_copy_due(
        out.get('allowed_actions'),
        overlay,
    )
    meta = dict(out.get('workflow_metadata') or {})
    meta['hard_copy_gate_active'] = True
    meta['payment_collection_blocked'] = True
    out['workflow_metadata'] = meta
    return out
