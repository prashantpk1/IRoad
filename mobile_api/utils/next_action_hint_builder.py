"""
mobile_api/utils/next_action_hint_builder.py

Driver-facing next-step hints for Job Detail and Execute Action responses.
"""
from __future__ import annotations

from typing import Any


def build_next_action_hint(
    workflow: dict[str, Any] | None,
    pod_cod: dict[str, Any] | None,
    action_code: str | None = None,
    order_type: str = 'Credit',
) -> dict[str, Any]:
    """
    Build next_action_hint dict for mobile app.
    Tells the mobile app exactly what to do next after every API response.

    Rules cover:
      - Credit flow A1 through A10
      - COD flow with A9 payment
      - All blocking states
      - All waiting states
      - Special screen triggers
      - Terminal state (job closed)
    """
    workflow = workflow or {}
    pod_cod = pod_cod or {}

    allowed = workflow.get('allowed_actions', [])
    next_action = workflow.get('next_action', {})
    next_code = (next_action or {}).get('action_code', '')
    metadata = workflow.get('workflow_metadata', {}) or {}
    sub_stage = metadata.get('execution_sub_stage', '')
    operational_stage = metadata.get('operational_stage', '')
    current_stage = (workflow.get('current_stage') or '').strip()

    pod_pending = pod_cod.get('pod_pending', True)
    pod_compliant = pod_cod.get('pod_compliant', False)
    hard_pod_pending = pod_cod.get('hard_pod_pending', False)
    cod_pending = pod_cod.get('cod_pending', False)
    cod_collected = pod_cod.get('cod_collected', False)
    treasury_pending = pod_cod.get('treasury_pending', False)
    delivery_blocked = pod_cod.get('delivery_blocked', False)

    is_cod = (order_type or '').upper() == 'COD'
    is_closed = (
        operational_stage == 'Closed'
        or current_stage == 'Closed'
        or sub_stage == 'completion'
    )

    # TERMINAL STATE — Job is closed
    if is_closed or action_code == 'A10':
        return {
            'action': 'go_to_dashboard',
            'screen': 'dashboard',
            'reason': 'Job is complete. No more actions required.',
            'job_closed': True,
            'show_completion_screen': True,
        }

    # A10 is next — job about to close
    if next_code == 'A10':
        return {
            'action': 'execute_action',
            'screen': 'job_detail',
            'action_code': 'A10',
            'reason': 'All steps complete. Tap to close the job.',
            'job_closed': False,
            'show_completion_screen': False,
        }

    # A7 is next — must do POD capture first
    if next_code == 'A7':
        return {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'A7',
            'reason': (
                'Upload proof of delivery. '
                'Take photo of signed delivery note then submit POD.'
            ),
            'job_closed': False,
            'show_completion_screen': False,
        }

    # A9 is next — COD payment collection
    if next_code == 'A9':
        return {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'A9',
            'reason': (
                'Collect cash payment from customer. '
                'Enter exact amount received.'
            ),
            'job_closed': False,
            'show_completion_screen': False,
        }

    # A4 is next — needs camera for truck photos
    if next_code == 'A4':
        return {
            'action': 'execute_action_with_media',
            'screen': 'job_detail',
            'action_code': 'A4',
            'reason': (
                'Confirm cargo is loaded. '
                'Take at least 2 photos of loaded truck.'
            ),
            'requires_camera': True,
            'job_closed': False,
            'show_completion_screen': False,
        }

    # Normal next action available
    if next_code and allowed:
        action_names = {
            'A1': 'Start the job',
            'A2': 'Mark arrival at pickup',
            'A3': 'Start loading cargo',
            'A5': 'Depart to delivery location',
            'A6': 'Mark arrival at delivery',
            'A8': 'Confirm unloading complete',
        }
        label = action_names.get(next_code, f'Execute {next_code}')
        return {
            'action': 'execute_action',
            'screen': 'job_detail',
            'action_code': next_code,
            'reason': label,
            'job_closed': False,
            'show_completion_screen': False,
        }

    # No allowed actions — check why

    # Hard POD pending
    if hard_pod_pending:
        return {
            'action': 'go_to_hard_pod',
            'screen': 'hard_pod',
            'reason': (
                'Physical documents required. '
                'Submit hard copy delivery note.'
            ),
            'job_closed': False,
            'show_completion_screen': False,
        }

    # Delivery blocked by POD not compliant
    if delivery_blocked and not pod_compliant:
        return {
            'action': 'wait_for_ops',
            'screen': 'job_detail',
            'reason': (
                'Waiting for operations team to verify proof of delivery. '
                'You will be notified when verified.'
            ),
            'job_closed': False,
            'show_completion_screen': False,
        }

    # COD not collected yet
    if is_cod and not cod_collected and not cod_pending:
        return {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'action_code': 'A9',
            'reason': 'COD payment not collected yet. Collect cash from customer.',
            'job_closed': False,
            'show_completion_screen': False,
        }

    # Treasury processing
    if treasury_pending:
        return {
            'action': 'refresh_job_detail',
            'screen': 'job_detail',
            'reason': 'Payment processing. Pull to refresh in a moment.',
            'job_closed': False,
            'show_completion_screen': False,
        }

    # POD compliant, A8 done, waiting for Delivered
    if pod_compliant and not is_closed:
        if is_cod and not cod_collected:
            return {
                'action': 'go_to_payment_collection',
                'screen': 'collect_payment',
                'action_code': 'A9',
                'reason': (
                    'POD verified. Collect COD payment to close job.'
                ),
                'job_closed': False,
                'show_completion_screen': False,
            }
        return {
            'action': 'refresh_job_detail',
            'screen': 'job_detail',
            'reason': (
                'POD verified. Finalising delivery status. Pull to refresh.'
            ),
            'auto_refresh_seconds': 3,
            'job_closed': False,
            'show_completion_screen': False,
        }

    # Generic fallback
    return {
        'action': 'refresh_job_detail',
        'screen': 'job_detail',
        'reason': 'Pull to refresh for latest status.',
        'job_closed': False,
        'show_completion_screen': False,
    }
