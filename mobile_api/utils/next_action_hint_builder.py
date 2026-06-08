"""
mobile_api/utils/next_action_hint_builder.py

Driver-facing next-step hints for Job Detail and Execute Action responses.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.cod_amount import build_cod_payment_display
from tenant_workspace.models import TenantShipment


def _normalize_allowed_actions(actions: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if actions is None:
        return out
    for row in actions:
        if isinstance(row, dict):
            out.append(dict(row))
            continue
        out.append(
            {
                'action_code': str(getattr(row, 'action_code', '') or ''),
                'english_label': str(getattr(row, 'english_label', '') or ''),
            },
        )
    return out


def _column_shipment_status(
    workflow: dict[str, Any],
    shipment: Any | None,
) -> str:
    """DB column status (not log-derived authoritative status)."""
    if shipment is not None:
        return (getattr(shipment, 'shipment_status', '') or '').strip()
    reconciliation = workflow.get('reconciliation') or {}
    column = (reconciliation.get('column_status') or '').strip()
    if column:
        return column
    metadata = workflow.get('workflow_metadata') or {}
    return (
        (metadata.get('status_for_workflow') or '').strip()
        or (workflow.get('current_stage') or '').strip()
    )


def _enrich_collect_payment_hint(
    hint: dict[str, Any],
    *,
    shipment: Any | None,
    booking: Any | None = None,
) -> dict[str, Any]:
    if hint.get('screen') != 'collect_payment':
        return hint
    out = dict(hint)
    out.update(build_cod_payment_display(shipment=shipment, booking=booking))
    return out


def build_next_action_hint(
    workflow: dict[str, Any] | None = None,
    pod_cod: dict[str, Any] | None = None,
    action_code: str | None = None,
    order_type: str = 'Credit',
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    allowed_actions: Any | None = None,
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
    workflow = dict(workflow or {})
    pod_cod = pod_cod or {}

    if allowed_actions is not None:
        normalized = _normalize_allowed_actions(allowed_actions)
        workflow['allowed_actions'] = normalized
        if normalized and not workflow.get('next_action'):
            workflow['next_action'] = dict(normalized[0])

    allowed = workflow.get('allowed_actions', [])
    next_action = workflow.get('next_action', {})
    next_code = (next_action or {}).get('action_code', '')
    if not next_code and allowed:
        first = allowed[0] if isinstance(allowed[0], dict) else {}
        next_code = str(first.get('action_code') or '').strip()

    shipment_status = _column_shipment_status(workflow, shipment)
    is_job_closed = shipment_status == TenantShipment.ShipmentStatus.CLOSED

    pod_pending = pod_cod.get('pod_pending', True)
    pod_compliant = pod_cod.get('pod_compliant', False)
    hard_pod_pending = pod_cod.get('hard_pod_pending', False)
    cod_pending = pod_cod.get('cod_pending', False)
    cod_collected = pod_cod.get('cod_collected', False)
    treasury_pending = pod_cod.get('treasury_pending', False)
    delivery_blocked = pod_cod.get('delivery_blocked', False)

    is_cod = (order_type or '').upper() == 'COD'

    # TERMINAL STATE — shipment column Closed (Delivered still needs A10)
    if is_job_closed or action_code == 'A10':
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

    # A7 is next — must do POD capture first (hard copy step is inside POD section)
    if next_code == 'A7':
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'A7',
            'reason': (
                'Upload proof of delivery. '
                'Take photo evidence (video optional), then submit POD.'
            ),
            'job_closed': False,
            'show_completion_screen': False,
        }
        if hard_pod_pending:
            hint['reason'] = (
                'Upload proof of delivery in the POD section. '
                'Complete digital evidence, then hard-copy confirmation.'
            )
            hint['pod_capture_steps'] = [
                'digital_evidence',
                'hard_copy_confirmation',
            ]
        return hint

    # A7H is next — hard-copy checklist (not generic evidence capture)
    if next_code == 'A7H':
        return {
            'action': 'go_to_hard_copy_confirmation',
            'screen': 'hard_copy_confirmation',
            'action_code': 'A7H',
            'reason': (
                'Confirm each signed delivery note page you collected, '
                'then submit hard POD custody.'
            ),
            'job_closed': False,
            'show_completion_screen': False,
        }

    # A9 is next — COD payment collection
    if next_code == 'A9':
        return _enrich_collect_payment_hint(
            {
                'action': 'go_to_payment_collection',
                'screen': 'collect_payment',
                'action_code': 'A9',
                'reason': (
                    'Collect cash payment from customer. '
                    'Enter exact amount received.'
                ),
                'job_closed': False,
                'show_completion_screen': False,
            },
            shipment=shipment,
            booking=booking,
        )

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
        return _enrich_collect_payment_hint(
            {
                'action': 'go_to_payment_collection',
                'screen': 'collect_payment',
                'action_code': 'A9',
                'reason': 'COD payment not collected yet. Collect cash from customer.',
                'job_closed': False,
                'show_completion_screen': False,
            },
            shipment=shipment,
            booking=booking,
        )

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
    if pod_compliant and not is_job_closed:
        if is_cod and not cod_collected:
            return _enrich_collect_payment_hint(
                {
                    'action': 'go_to_payment_collection',
                    'screen': 'collect_payment',
                    'action_code': 'A9',
                    'reason': (
                        'POD verified. Collect COD payment to close job.'
                    ),
                    'job_closed': False,
                    'show_completion_screen': False,
                },
                shipment=shipment,
                booking=booking,
            )
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
