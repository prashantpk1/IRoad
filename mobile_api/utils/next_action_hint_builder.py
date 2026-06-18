"""
mobile_api/utils/next_action_hint_builder.py

Driver-facing next-step hints for Job Detail and Execute Action responses.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
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


def _hard_copy_confirmation_hint(*, reason: str = '') -> dict[str, Any]:
    return {
        'action': 'go_to_pod_capture',
        'screen': 'pod_capture',
        'action_code': 'A7H',
        'capture_mode': 'hard_copy_confirmation',
        'active_step': 'hard_copy_confirmation',
        'ui_mode': 'hard_pod_collection_confirmation',
        'screen_title': 'Hard POD Collection Confirmation',
        'pod_capture_steps': ['hard_copy_confirmation'],
        'reason': reason
        or (
            'Digital POD is uploaded. Confirm hard-copy delivery note pages '
            'inside Upload POD, then continue.'
        ),
        'job_closed': False,
        'show_completion_screen': False,
    }


def _hard_copy_applicable(pod_cod: dict[str, Any]) -> bool:
    block = dict(pod_cod.get('hard_copy_confirmation') or {})
    return bool(block.get('applicable') or block.get('required'))


def _hard_copy_step_required(pod_cod: dict[str, Any]) -> bool:
    if pod_cod.get('pod_pending'):
        return False
    if not pod_cod.get('hard_pod_pending'):
        return False
    return _hard_copy_applicable(pod_cod)


def _resolve_round_trip_return_open_job(
    booking: Any | None,
    *,
    driver: Any | None = None,
) -> dict[str, Any] | None:
    """
    When outbound is done but backload has no shipment row yet, tell mobile to
    open the booking-scoped return leg from the dashboard card.
    """
    if booking is None:
        return None
    from mobile_api.job_detail.helpers.booking_job_context import load_booking_shipments

    shipments = load_booking_shipments(booking)
    if not booking_policy.is_backload_leg_pending(booking, shipments):
        return None
    if driver is not None and not booking_policy.driver_owns_backload_leg(
        driver,
        booking,
    ):
        return None
    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    return {
        'job_type': 'booking',
        'job_id': str(booking_id) if booking_id is not None else '',
        'job_no': str(getattr(booking, 'booking_no', '') or ''),
        'booking_item_type': 'Backload',
        'backload_bootstrap_pending': True,
    }


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


def _close_job_hint() -> dict[str, Any]:
    return {
        'action': 'execute_action',
        'screen': 'job_detail',
        'action_code': 'A10',
        'reason': 'All steps complete. Tap to close the job.',
        'job_closed': False,
        'show_completion_screen': False,
        'show_close_job_button': True,
        'direct_execute': True,
    }


def _a10_in_allowed_actions(allowed: list[Any]) -> bool:
    for row in allowed:
        if not isinstance(row, dict):
            continue
        if str(row.get('action_code') or '').strip().upper() == 'A10':
            return True
    return False


def _job_close_ready_for_hint(
    *,
    pod_cod: dict[str, Any],
    order_type: str,
    is_job_closed: bool,
    shipment_status: str,
) -> bool:
    """Driver may close the job when POD/COD gates pass (POD Submitted or Delivered)."""
    if is_job_closed:
        return False
    if _hard_copy_step_required(pod_cod):
        return False
    if pod_cod.get('treasury_pending'):
        return False
    if pod_cod.get('delivery_blocked') and not pod_cod.get('pod_compliant'):
        return False
    if not pod_cod.get('pod_compliant'):
        return False
    is_cod = (order_type or '').upper() == 'COD'
    if is_cod and not pod_cod.get('cod_collected'):
        return False
    return (shipment_status or '').strip() in {
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }


def build_next_action_hint(
    workflow: dict[str, Any] | None = None,
    pod_cod: dict[str, Any] | None = None,
    action_code: str | None = None,
    order_type: str = 'Credit',
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    driver: Any | None = None,
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
    if shipment is not None:
        shipment_status = (
            (getattr(shipment, 'shipment_status', None) or '').strip()
            or shipment_status
        )
    is_job_closed = shipment_status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }

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
        open_job = _resolve_round_trip_return_open_job(booking, driver=driver)
        hint: dict[str, Any] = {
            'action': 'go_to_dashboard',
            'screen': 'dashboard',
            'job_closed': True,
            'show_completion_screen': True,
        }
        if open_job:
            hint.update(
                {
                    'reason': (
                        'Outbound trip complete. Tap Open Job on My Jobs to '
                        'start the return trip.'
                    ),
                    'leg_completed': True,
                    'booking_continues': True,
                    'open_job': open_job,
                },
            )
        else:
            hint['reason'] = 'Job is complete. No more actions required.'
        return hint

    # A10 is next — job about to close
    if next_code == 'A10':
        return _close_job_hint()

    # A7 is next — open digital evidence capture (hard copy is a later A7H step)
    if next_code == 'A7':
        hard_copy_applicable = _hard_copy_applicable(pod_cod)
        hint = {
            'action': 'go_to_pod_capture',
            'screen': 'pod_capture',
            'action_code': 'A7',
            'capture_mode': 'digital_evidence',
            'ui_mode': 'digital_evidence',
            'active_step': 'digital_evidence',
            'screen_title': 'Capturing Action Evidences',
            'reason': (
                'Upload proof of delivery. Capture photos and video evidence, '
                'then tap Next.'
            ),
            'pod_capture_steps': ['digital_evidence'],
            'job_closed': False,
            'show_completion_screen': False,
        }
        if hard_copy_applicable:
            hint['pod_capture_steps'] = [
                'digital_evidence',
                'hard_copy_confirmation',
            ]
            block = dict(pod_cod.get('hard_copy_confirmation') or {})
            hint['documents_endpoint'] = block.get('documents_endpoint') or ''
            hint['custody_submit_endpoint'] = block.get('submit_endpoint') or ''
        return hint

    # Just finished digital A7 — open hard-copy step 2 before any forward action
    if (action_code or '').strip().upper() == 'A7' and _hard_copy_step_required(pod_cod):
        return _hard_copy_confirmation_hint()

    # Hard POD step 2 blocks A8/A9/A10 until custody confirmed
    if _hard_copy_step_required(pod_cod) and next_code in {
        'A7',
        'A7H',
        'A8',
        'A9',
        'A10',
        '',
    }:
        return _hard_copy_confirmation_hint()

    # A1 — booking start: direct execute, no evidence wizard
    if next_code == 'A1':
        return {
            'action': 'execute_action',
            'screen': 'job_detail',
            'action_code': 'A1',
            'direct_execute': True,
            'requires_evidence_capture': False,
            'reason': 'Start the job.',
            'job_closed': False,
            'show_completion_screen': False,
        }

    # A8 — unloading is GPS-only (only after hard copy complete on Hard POD)
    if next_code == 'A8':
        return {
            'action': 'execute_action',
            'screen': 'job_detail',
            'action_code': 'A8',
            'reason': 'Confirm unloading complete.',
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

    # No allowed actions — job finished
    if is_job_closed:
        return {
            'action': 'go_to_dashboard',
            'screen': 'dashboard',
            'reason': 'Job is complete. No more actions required.',
            'job_closed': True,
            'show_completion_screen': True,
        }

    # Hard copy still due with no forward action left (e.g. after A9 without A7H)
    if _hard_copy_step_required(pod_cod) and not pod_compliant:
        return _hard_copy_confirmation_hint(
            reason=(
                'Complete hard-copy POD confirmation inside Upload POD, '
                'then close the job.'
            ),
        )

    # Delivery blocked by POD not compliant (portal / column validation)
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

    # POD + COD complete — show Close Job even when workflow lags (e.g. POD Submitted)
    if _job_close_ready_for_hint(
        pod_cod=pod_cod,
        order_type=order_type,
        is_job_closed=is_job_closed,
        shipment_status=shipment_status,
    ) and (
        next_code == 'A10'
        or _a10_in_allowed_actions(allowed)
        or not next_code
    ):
        return _close_job_hint()

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
        if _job_close_ready_for_hint(
            pod_cod=pod_cod,
            order_type=order_type,
            is_job_closed=is_job_closed,
            shipment_status=shipment_status,
        ):
            return _close_job_hint()
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
