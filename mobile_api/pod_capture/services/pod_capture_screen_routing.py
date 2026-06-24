"""
mobile_api/pod_capture/services/pod_capture_screen_routing.py

Top-level screen hints for POD / Hard POD capture GET responses.
"""
from __future__ import annotations

from typing import Any

from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
    CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
)
from mobile_api.pod_capture.services.pod_section_metadata import (
    DIGITAL_EVIDENCE_SCREEN_TITLE,
    HARD_COPY_SCREEN_TITLE,
    UI_MODE_DIGITAL_EVIDENCE,
    UI_MODE_HARD_POD_CONFIRMATION,
    build_pod_capture_steps,
)

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
    digital_block = dict(pod_section.get('digital_evidence') or {})
    hard_applicable = bool(hard_block.get('applicable') or hard_block.get('required'))
    hard_pending = bool(pod_section.get('hard_pod_pending')) or bool(
        hard_block.get('pending')
    )
    digital_complete = bool(pod_section.get('digital_evidence_complete'))

    # Step 1 is always digital on first open. Step 2 (hard copy) when:
    # - client requests ``?step=hard_copy_confirmation``, or
    # - digital POD is done and hard custody is still outstanding (resume).
    if step in {'hard_copy', 'hard_copy_confirmation', 'a7h'} or (
        hard_applicable and hard_pending and digital_complete
    ):
        return {
            'screen': POD_CAPTURE_SCREEN,
            'capture_mode': HARD_COPY_CONFIRMATION_SCREEN,
            'active_step': 'hard_copy_confirmation',
            'action': 'go_to_pod_capture',
            'action_code': (
                hard_block.get('execute_action_code')
                or CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE
            ).strip(),
            'pod_capture_steps': build_pod_capture_steps(hard_pod=True),
            'screen_title': HARD_COPY_SCREEN_TITLE,
            'ui_mode': UI_MODE_HARD_POD_CONFIRMATION,
        }

    capture_steps = list(pod_section.get('capture_steps') or ['digital_evidence'])
    return {
        'screen': POD_CAPTURE_SCREEN,
        'capture_mode': UI_MODE_DIGITAL_EVIDENCE,
        'active_step': 'digital_evidence',
        'action': 'go_to_pod_capture',
        'action_code': (
            digital_block.get('execute_action_code')
            or CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE
        ).strip(),
        'ui_mode': UI_MODE_DIGITAL_EVIDENCE,
        'pod_capture_steps': capture_steps,
        'screen_title': DIGITAL_EVIDENCE_SCREEN_TITLE,
    }
