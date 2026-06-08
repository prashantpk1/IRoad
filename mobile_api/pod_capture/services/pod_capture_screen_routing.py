"""
mobile_api/pod_capture/services/pod_capture_screen_routing.py

Top-level screen hints for POD / Hard POD capture GET responses.
"""
from __future__ import annotations

from typing import Any

HARD_COPY_CONFIRMATION_SCREEN = 'hard_copy_confirmation'
POD_CAPTURE_SCREEN = 'pod_capture'


def build_pod_capture_get_routing(
    pod_section: dict[str, Any],
    *,
    requested_step: str = '',
) -> dict[str, str]:
    """
    Tell mobile which screen to open for ``GET .../pod/capture/``.

    When hard-copy custody is outstanding, route to the checklist — not generic
    GPS/photo evidence capture.
    """
    step = (requested_step or '').strip().casefold()
    hard_block = dict(pod_section.get('hard_copy_confirmation') or {})
    hard_pending = bool(pod_section.get('hard_pod_pending')) or bool(
        hard_block.get('pending')
    )
    hard_required = bool(hard_block.get('required'))

    if step in {'hard_copy', 'hard_copy_confirmation', 'a7h'} or (
        hard_required and hard_pending
    ):
        return {
            'screen': HARD_COPY_CONFIRMATION_SCREEN,
            'capture_mode': HARD_COPY_CONFIRMATION_SCREEN,
            'active_step': 'hard_copy_confirmation',
            'action': 'go_to_hard_copy_confirmation',
            'action_code': (hard_block.get('execute_action_code') or 'A7H').strip(),
        }

    return {
        'screen': POD_CAPTURE_SCREEN,
        'capture_mode': 'digital_evidence',
        'active_step': 'digital_evidence',
        'action': 'go_to_pod_capture',
        'action_code': 'A7',
    }
