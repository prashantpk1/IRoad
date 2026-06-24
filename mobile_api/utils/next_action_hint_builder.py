"""
mobile_api/utils/next_action_hint_builder.py

Driver-facing next-step hints for Job Detail and Execute Action responses.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.helpers.cod_amount import build_cod_payment_display
from mobile_api.helpers.job_action_resolver import (
    action_code_is_collect_payment,
    action_code_is_job_close,
    resolve_collect_payment_action_code_from_context,
    resolve_job_close_action_code_from_context,
    resolve_unloading_action_code_from_context,
    row_action_reason_label,
    row_is_collect_payment_action,
    row_is_confirm_loaded_action,
    row_is_job_close_action,
    row_is_start_job_action,
    row_is_unloading_action,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
    CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
    resolve_digital_pod_action_code_from_context,
    resolve_hard_copy_action_code_from_context,
    row_has_digital_pod_upload,
    row_has_hard_copy_collection,
)
from mobile_api.pod_capture.services.pod_section_metadata import build_pod_capture_steps
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    shipment_unloading_done,
)
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


def _hard_copy_confirmation_hint(
    *,
    reason: str = '',
    pod_cod: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    action_code = resolve_hard_copy_action_code_from_context(
        pod_cod=pod_cod,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )
    default_reason = (
        'Digital POD is uploaded. Confirm hard-copy delivery note pages '
        'inside Upload POD before collecting payment.'
    )
    return {
        'action': 'go_to_pod_capture',
        'screen': 'pod_capture',
        'action_code': action_code,
        'capture_mode': 'hard_copy_confirmation',
        'active_step': 'hard_copy_confirmation',
        'ui_mode': 'hard_pod_collection_confirmation',
        'screen_title': 'Hard POD Collection Confirmation',
        'pod_capture_steps': build_pod_capture_steps(hard_pod=True),
        'reason': reason or default_reason,
        'job_closed': False,
        'show_completion_screen': False,
    }


def _build_digital_pod_capture_hint(
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    *,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Step 1 — digital evidence wizard (step 2 when Hard POD)."""
    hard_copy_applicable = _hard_copy_applicable(pod_cod)
    digital_code = resolve_digital_pod_action_code_from_context(
        pod_cod=pod_cod,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )
    hint: dict[str, Any] = {
        'action': 'go_to_pod_capture',
        'screen': 'pod_capture',
        'action_code': digital_code,
        'capture_mode': 'digital_evidence',
        'ui_mode': 'digital_evidence',
        'active_step': 'digital_evidence',
        'screen_title': 'Capturing Action Evidences',
        'reason': (
            'Upload proof of delivery. Capture photos and video evidence, '
            'then tap Next.'
        ),
        'pod_capture_steps': build_pod_capture_steps(hard_pod=hard_copy_applicable),
        'hard_pod': hard_copy_applicable,
        'job_closed': False,
        'show_completion_screen': False,
    }
    if hard_copy_applicable:
        block = dict(pod_cod.get('hard_copy_confirmation') or {})
        hint['documents_endpoint'] = block.get('documents_endpoint') or ''
        hint['custody_submit_endpoint'] = block.get('submit_endpoint') or ''
    return hint


def align_next_action_hint_with_workflow(
    hint: dict[str, Any],
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    *,
    tenant_schema: str = '',
    shipment: Any | None = None,
    booking: Any | None = None,
    driver: Any | None = None,
) -> dict[str, Any]:
    """
    Ensure ``next_action_hint`` matches workflow POD navigation (digital first).

    Mobile should trust ``next_action_hint`` — keep it aligned with
    ``workflow.primary_action`` / ``allowed_actions`` POD rows.
    """
    workflow = dict(workflow or {})
    pod_cod = dict(pod_cod or {})
    primary = dict(workflow.get('primary_action') or {})
    code = str(
        hint.get('action_code')
        or primary.get('action_code')
        or (workflow.get('next_action') or {}).get('action_code')
        or ''
    ).strip()
    row = _resolve_action_row(workflow, code) or primary

    if (
        row_is_collect_payment_action(primary)
        or row_is_collect_payment_action(row)
        or row_is_collect_payment_action(hint)
    ):
        if pod_cod.get('pod_pending'):
            return _finalize_hint(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        if _unloading_step_due(shipment, workflow):
            return _finalize_hint(
                _build_unloading_execute_hint(
                    workflow,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        if (
            not pod_cod.get('cod_collected')
            and (
                str(hint.get('action') or '') == 'go_to_payment_collection'
                or str(hint.get('screen') or '') == 'collect_payment'
            )
        ):
            resolved_booking = booking or getattr(shipment, 'booking', None)
            return _finalize_hint(
                _build_collect_payment_timeline_hint(
                    workflow=workflow,
                    tenant_schema=tenant_schema,
                    next_code=code,
                    shipment=shipment,
                    booking=resolved_booking,
                    pod_submitted=bool(hint.get('pod_submitted')),
                ),
                workflow,
            )

    if _hard_copy_step_required(pod_cod) and (
        row_is_collect_payment_action(primary)
        or row_is_collect_payment_action(row)
        or row_is_collect_payment_action(hint)
    ):
        return _finalize_hint(
            _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
            workflow,
        )

    if not _hard_copy_step_required(pod_cod):
        allowed = workflow.get('allowed_actions') or []
        if row_is_job_close_action(primary) or _job_close_in_allowed_actions(allowed):
            if str(hint.get('action') or '') == 'go_to_pod_capture':
                resolved_booking = booking or getattr(shipment, 'booking', None)
                return _finalize_close_or_round_trip_continue_hint(
                    workflow=workflow,
                    tenant_schema=tenant_schema,
                    booking=resolved_booking,
                    shipment=shipment,
                    driver=driver,
                )
            shipment_status = _column_shipment_status(workflow, shipment)
            if shipment is not None:
                shipment_status = (
                    (getattr(shipment, 'shipment_status', None) or '').strip()
                    or shipment_status
                )
            if _job_close_ready_for_hint(
                pod_cod=pod_cod,
                order_type=str(
                    getattr(shipment, 'order_type', None) or ''
                ),
                is_job_closed=shipment_status
                in {
                    TenantShipment.ShipmentStatus.CLOSED,
                    TenantShipment.ShipmentStatus.CANCELLED,
                },
                shipment_status=shipment_status,
            ):
                return _finalize_hint(
                    _close_job_hint(
                        workflow=workflow,
                        tenant_schema=tenant_schema,
                    ),
                    workflow,
                )

    if pod_cod.get('pod_pending') and row_has_digital_pod_upload(row):
        if str(hint.get('action') or '') != 'go_to_pod_capture':
            return _finalize_hint(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        return _merge_pod_navigation_from_workflow_row(
            _finalize_hint(dict(hint), workflow),
            workflow,
        )

    if _hard_copy_step_required(pod_cod) and str(hint.get('action') or '') != 'go_to_pod_capture':
        return _finalize_hint(
            _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
            workflow,
        )

    return _merge_pod_navigation_from_workflow_row(_finalize_hint(dict(hint), workflow), workflow)


def _merge_pod_navigation_from_workflow_row(
    hint: dict[str, Any],
    workflow: dict[str, Any],
) -> dict[str, Any]:
    """Copy POD wizard contract from primary/next action when already projected."""
    code = str(hint.get('action_code') or '').strip()
    if not code:
        return hint
    row = _resolve_action_row(workflow, code) or dict(workflow.get('primary_action') or {})
    if not row_has_digital_pod_upload(row) and not row_has_hard_copy_collection(row):
        return hint
    if str(row.get('action') or '') != 'go_to_pod_capture':
        return hint
    out = dict(hint)
    for key in (
        'action',
        'screen',
        'capture_mode',
        'active_step',
        'ui_mode',
        'screen_title',
        'pod_capture_steps',
        'hard_pod',
        'includes_hard_copy',
        'capture_ui',
        'hard_copy_confirmation',
        'confirmation_ui',
    ):
        if key in row and row[key] not in (None, '', []):
            out[key] = row[key]
    if out.get('action') == 'go_to_pod_capture':
        out['requires_multipart'] = False
    return out


def _is_digital_pod_next(workflow: dict[str, Any], next_code: str) -> bool:
    if not (next_code or '').strip():
        return False
    row = _resolve_action_row(workflow, next_code)
    if row_has_digital_pod_upload(row):
        return True
    code = (next_code or '').strip().upper()
    return code == CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE


def _is_hard_copy_pod_next(workflow: dict[str, Any], next_code: str) -> bool:
    row = _resolve_action_row(workflow, next_code)
    return row_has_hard_copy_collection(row)


def _executed_digital_pod_upload(
    workflow: dict[str, Any],
    action_code: str | None,
) -> bool:
    row = _resolve_action_row(workflow, action_code or '')
    if row_has_digital_pod_upload(row):
        return True
    code = (action_code or '').strip().upper()
    return code in {'OA-0008', 'A7', CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE}


def _pod_execute_just_completed(
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    action_code: str | None,
) -> bool:
    """True only on the execute-action response immediately after digital POD."""
    if not (action_code or '').strip():
        return False
    if not _executed_digital_pod_upload(workflow, action_code):
        return False
    return bool(pod_cod.get('pod_compliant')) and not pod_cod.get('pod_pending')


def _collect_payment_execute_just_completed(
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    action_code: str | None,
) -> bool:
    """True only on the execute-action response immediately after COD collection."""
    if not (action_code or '').strip():
        return False
    row = _resolve_action_row(workflow, action_code)
    if not (
        row_is_collect_payment_action(row)
        or action_code_is_collect_payment(action_code)
    ):
        return False
    return bool(pod_cod.get('cod_collected')) and not pod_cod.get('treasury_pending')


def _hard_copy_hint(
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    *,
    reason: str = '',
    tenant_schema: str = '',
) -> dict[str, Any]:
    return _hard_copy_confirmation_hint(
        reason=reason,
        pod_cod=pod_cod,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )


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


def _round_trip_leg_complete_continue_hint(
    booking: Any | None,
    *,
    driver: Any | None = None,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Outbound leg finished — continue return trip instead of Job Close."""
    open_job = _resolve_round_trip_return_open_job(booking, driver=driver)
    hint: dict[str, Any] = {
        'action': 'go_to_dashboard',
        'screen': 'dashboard',
        'job_closed': False,
        'show_completion_screen': True,
        'leg_completed': True,
        'booking_continues': True,
    }
    if open_job:
        hint['open_job'] = open_job
        hint['reason'] = (
            'Outbound trip complete. Tap Open Job on My Jobs to '
            'start the return trip.'
        )
    else:
        hint['reason'] = (
            'Outbound leg complete. Continue the return trip from My Jobs.'
        )
    return hint


def _finalize_job_close_timeline_hint(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    payment_collected: bool = False,
) -> dict[str, Any]:
    """Stay on job detail; driver closes the job from the timeline row."""
    workflow = dict(workflow or {})
    hint = dict(_close_job_hint(workflow=workflow, tenant_schema=tenant_schema))
    if payment_collected:
        hint.update(
            {
                'reason': (
                    'Payment collected successfully. Tap Job Close to finish '
                    'this leg.'
                ),
                'show_completion_screen': True,
                'payment_collected': True,
            },
        )
    return _finalize_hint(hint, workflow)


def _finalize_close_or_round_trip_continue_hint(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    booking: Any | None = None,
    shipment: Any | None = None,
    driver: Any | None = None,
    payment_collected: bool = False,
) -> dict[str, Any]:
    _ = (booking, shipment, driver)
    return _finalize_job_close_timeline_hint(
        workflow=workflow,
        tenant_schema=tenant_schema,
        payment_collected=payment_collected,
    )


def _build_collect_payment_timeline_hint(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    next_code: str = '',
    shipment: Any | None = None,
    booking: Any | None = None,
    reason: str = '',
    pod_submitted: bool = False,
) -> dict[str, Any]:
    """
  Collect Payment navigation.

  - Right after POD execute (``pod_submitted``): stay on timeline.
  - Job Detail / button tap: open payment collection screen.
    """
    from mobile_api.helpers.action_navigation_metadata import (
        PAYMENT_COLLECT_API_PATH,
    )

    default_reason = (
        'POD submitted successfully. Tap Collect Payment on the timeline '
        'to continue.'
        if pod_submitted
        else 'Collect cash from the customer to continue.'
    )
    if pod_submitted:
        action = 'refresh_job_detail'
        screen = 'job_detail'
    else:
        action = 'go_to_payment_collection'
        screen = 'collect_payment'
    hint: dict[str, Any] = {
        'action': action,
        'screen': screen,
        'action_code': resolve_collect_payment_action_code_from_context(
            workflow=workflow,
            tenant_schema=tenant_schema,
            next_code=next_code,
        ),
        'reason': reason or default_reason,
        'job_closed': False,
        'show_completion_screen': pod_submitted,
        'pod_submitted': pod_submitted,
        'ui_mode': 'collect_payment',
        'screen_title': 'Collect Payment',
        'direct_execute': False,
        'payment_collect_endpoint': PAYMENT_COLLECT_API_PATH,
    }
    hint.update(build_cod_payment_display(shipment=shipment, booking=booking))
    return hint


def _resolve_action_row(workflow: dict[str, Any], action_code: str) -> dict[str, Any]:
    code = (action_code or '').strip().upper()
    if not code:
        return {}
    for row in workflow.get('allowed_actions') or []:
        if isinstance(row, dict) and str(row.get('action_code') or '').strip().upper() == code:
            return row
    next_action = workflow.get('next_action') or {}
    if str(next_action.get('action_code') or '').strip().upper() == code:
        return dict(next_action)
    primary = workflow.get('primary_action') or {}
    if str(primary.get('action_code') or '').strip().upper() == code:
        return dict(primary)
    return {}


def _requires_multipart_for_action(
    row: dict[str, Any],
    *,
    capture_mode: str = '',
) -> bool:
    """True when execute should use multipart (photos / auto_shipment_post)."""
    req = dict(row.get('execution_requirements') or {})
    if req.get('auto_shipment_post') is True:
        return True
    photo_min = int(req.get('photo_min_count') or 0)
    if req.get('photo') is True and photo_min >= 1:
        return True
    if capture_mode in {'photo_evidence', 'loading_photos'}:
        return True
    return False


def _finalize_hint(hint: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    """Attach driver-facing flags derived from workflow execution_requirements."""
    out = dict(hint)
    action = str(out.get('action') or '')
    code = str(out.get('action_code') or '').strip()
    if action == 'execute_action_with_media':
        out['requires_multipart'] = True
    elif action == 'execute_action' and code:
        row = _resolve_action_row(workflow, code)
        out['requires_multipart'] = _requires_multipart_for_action(
            row,
            capture_mode=str(out.get('capture_mode') or ''),
        )
    else:
        out['requires_multipart'] = False
    return out


def _close_job_hint(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    return {
        'action': 'execute_action',
        'screen': 'job_detail',
        'ui_mode': 'job_close',
        'action_code': resolve_job_close_action_code_from_context(
            workflow=workflow,
            tenant_schema=tenant_schema,
        ),
        'reason': 'All steps complete. Tap Job Close to finish this leg.',
        'job_closed': False,
        'show_completion_screen': False,
        'payment_collected': False,
        'show_close_job_button': True,
        'direct_execute': True,
        'requires_gps': False,
        'requires_photo': False,
        'requires_video': False,
        'requires_note': False,
        'requires_evidence_capture': False,
        'requires_multipart': False,
    }


def _job_close_in_allowed_actions(allowed: list[Any]) -> bool:
    for row in allowed:
        if isinstance(row, dict) and row_is_job_close_action(row):
            return True
    return False


def _is_collect_payment_next(workflow: dict[str, Any], next_code: str) -> bool:
    return row_is_collect_payment_action(_resolve_action_row(workflow, next_code))


def _is_unloading_next(workflow: dict[str, Any], next_code: str) -> bool:
    return row_is_unloading_action(_resolve_action_row(workflow, next_code))


def _unloading_step_due(
    shipment: Any | None,
    workflow: dict[str, Any],
    shipment_status: str = '',
) -> bool:
    if shipment is None:
        return False
    status = (
        (shipment_status or '').strip()
        or (getattr(shipment, 'shipment_status', None) or '').strip()
    )
    if status != TenantShipment.ShipmentStatus.AT_DELIVERY:
        return False
    if shipment_unloading_done(shipment):
        return False
    for row in workflow.get('allowed_actions') or []:
        if isinstance(row, dict) and row_is_unloading_action(row):
            return True
    return False


def _build_unloading_execute_hint(
    workflow: dict[str, Any],
    *,
    tenant_schema: str = '',
    action_code: str = '',
) -> dict[str, Any]:
    code = (
        (action_code or '').strip()
        or resolve_unloading_action_code_from_context(
            workflow=workflow,
            tenant_schema=tenant_schema,
        )
    )
    return {
        'action': 'execute_action',
        'screen': 'job_detail',
        'action_code': code,
        'direct_execute': True,
        'reason': 'Confirm start unloading at delivery site.',
        'job_closed': False,
        'show_completion_screen': False,
    }


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
    tenant_schema: str = '',
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
    pod_just_submitted = _pod_execute_just_completed(workflow, pod_cod, action_code)
    payment_just_collected = _collect_payment_execute_just_completed(
        workflow,
        pod_cod,
        action_code,
    )

    # TERMINAL STATE — shipment column Closed (Delivered still needs job close)
    if is_job_closed or action_code_is_job_close(
        action_code,
        workflow=workflow,
        tenant_schema=tenant_schema,
    ):
        open_job = _resolve_round_trip_return_open_job(booking, driver=driver)
        booking_continues = bool(open_job)
        hint: dict[str, Any] = {
            'action': 'go_to_dashboard',
            'screen': 'dashboard',
            'job_closed': not booking_continues,
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
        return _finalize_hint(hint, workflow)

    # Job close is next — resolve tenant code from workflow / Action Master.
    if next_code and row_is_job_close_action(_resolve_action_row(workflow, next_code)):
        return _finalize_close_or_round_trip_continue_hint(
            workflow=workflow,
            tenant_schema=tenant_schema,
            booking=booking,
            shipment=shipment,
            driver=driver,
            payment_collected=payment_just_collected,
        )

    # Hard copy custody still due — resume Upload POD step 2 before forward actions.
    if _hard_copy_step_required(pod_cod):
        return _finalize_hint(
            _hard_copy_hint(
                workflow,
                pod_cod,
                tenant_schema=tenant_schema,
            ),
            workflow,
        )

    # Start Unloading at delivery — before POD upload and COD collection.
    if _unloading_step_due(shipment, workflow, shipment_status):
        return _finalize_hint(
            _build_unloading_execute_hint(
                workflow,
                tenant_schema=tenant_schema,
            ),
            workflow,
        )

    # Digital POD upload is next — open evidence capture wizard step 1.
    if pod_pending and _is_digital_pod_next(workflow, next_code):
        return _finalize_hint(
            _build_digital_pod_capture_hint(
                workflow,
                pod_cod,
                tenant_schema=tenant_schema,
            ),
            workflow,
        )

    next_row = _resolve_action_row(workflow, next_code) if next_code else {}

    # Start job — direct execute, no evidence wizard (tenant-specific code).
    if next_code and row_is_start_job_action(next_row):
        return _finalize_hint(
            {
                'action': 'execute_action',
                'screen': 'job_detail',
                'action_code': next_code,
                'direct_execute': True,
                'requires_evidence_capture': False,
                'reason': row_action_reason_label(next_row, next_code),
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
        )

    # Start Unloading — GPS-only confirm at delivery site (tenant-specific code).
    if _is_unloading_next(workflow, next_code):
        return _finalize_hint(
            _build_unloading_execute_hint(
                workflow,
                tenant_schema=tenant_schema,
                action_code=next_code,
            ),
            workflow,
        )

    # COD already collected — Job Close is next even when workflow still lists payment.
    if (
        is_cod
        and cod_collected
        and not treasury_pending
        and _job_close_ready_for_hint(
            pod_cod=pod_cod,
            order_type=order_type,
            is_job_closed=is_job_closed,
            shipment_status=shipment_status,
        )
    ):
        return _finalize_close_or_round_trip_continue_hint(
            workflow=workflow,
            tenant_schema=tenant_schema,
            booking=booking,
            shipment=shipment,
            driver=driver,
            payment_collected=payment_just_collected,
        )

    # COD payment collection is next — only after unloading and POD gates pass.
    if _is_collect_payment_next(workflow, next_code):
        if pod_pending:
            if _is_digital_pod_next(workflow, next_code) or any(
                row_has_digital_pod_upload(row)
                for row in allowed
                if isinstance(row, dict)
            ):
                return _finalize_hint(
                    _build_digital_pod_capture_hint(
                        workflow,
                        pod_cod,
                        tenant_schema=tenant_schema,
                    ),
                    workflow,
                )
        if _unloading_step_due(shipment, workflow, shipment_status):
            return _finalize_hint(
                _build_unloading_execute_hint(
                    workflow,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        return _finalize_hint(
            _build_collect_payment_timeline_hint(
                workflow=workflow,
                tenant_schema=tenant_schema,
                next_code=next_code,
                shipment=shipment,
                booking=booking,
                pod_submitted=pod_just_submitted,
            ),
            workflow,
        )
    if next_code and row_is_confirm_loaded_action(next_row):
        return _finalize_hint(
            {
                'action': 'execute_action_with_media',
                'screen': 'job_detail',
                'action_code': next_code,
                'reason': (
                    row_action_reason_label(next_row, next_code)
                    or 'Confirm cargo is loaded. '
                    'Take at least 2 photos of loaded truck.'
                ),
                'requires_camera': True,
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
        )

    # Normal next action available
    if next_code and allowed:
        row = _resolve_action_row(workflow, next_code)
        if pod_pending and row_has_digital_pod_upload(row):
            return _finalize_hint(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        label = row_action_reason_label(row, next_code)
        return _finalize_hint(
            {
                'action': 'execute_action',
                'screen': 'job_detail',
                'action_code': next_code,
                'reason': label,
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
        )

    # No allowed actions — job finished
    if is_job_closed:
        return _finalize_hint(
            {
                'action': 'go_to_dashboard',
                'screen': 'dashboard',
                'reason': 'Job is complete. No more actions required.',
                'job_closed': True,
                'show_completion_screen': True,
            },
            workflow,
        )

    # No allowed actions — job finished
    if delivery_blocked and not pod_compliant:
        return _finalize_hint(
            {
                'action': 'wait_for_ops',
                'screen': 'job_detail',
                'reason': (
                    'Waiting for operations team to verify proof of delivery. '
                    'You will be notified when verified.'
                ),
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
        )

    # COD not collected yet — respect unloading and POD order first.
    if is_cod and not cod_collected and not cod_pending:
        if _hard_copy_step_required(pod_cod):
            return _finalize_hint(
                _hard_copy_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        if pod_pending:
            digital_code = resolve_digital_pod_action_code_from_context(
                pod_cod=pod_cod,
                workflow=workflow,
                tenant_schema=tenant_schema,
            )
            if digital_code:
                return _finalize_hint(
                    _build_digital_pod_capture_hint(
                        workflow,
                        pod_cod,
                        tenant_schema=tenant_schema,
                    ),
                    workflow,
                )
        if _unloading_step_due(shipment, workflow, shipment_status):
            return _finalize_hint(
                _build_unloading_execute_hint(
                    workflow,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        if not pod_compliant or pod_pending:
            return _finalize_hint(
                {
                    'action': 'refresh_job_detail',
                    'screen': 'job_detail',
                    'reason': 'Complete proof of delivery before collecting payment.',
                    'job_closed': False,
                    'show_completion_screen': False,
                },
                workflow,
            )
        return _finalize_hint(
            _build_collect_payment_timeline_hint(
                workflow=workflow,
                tenant_schema=tenant_schema,
                shipment=shipment,
                booking=booking,
                pod_submitted=pod_just_submitted,
            ),
            workflow,
        )

    # Treasury processing
    if treasury_pending:
        return _finalize_hint(
            {
                'action': 'refresh_job_detail',
                'screen': 'job_detail',
                'reason': 'Payment processing. Pull to refresh in a moment.',
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
        )

    # POD + COD complete — show Close Job even when workflow lags (e.g. POD Submitted)
    if _job_close_ready_for_hint(
        pod_cod=pod_cod,
        order_type=order_type,
        is_job_closed=is_job_closed,
        shipment_status=shipment_status,
    ) and (
        row_is_job_close_action(_resolve_action_row(workflow, next_code))
        or _job_close_in_allowed_actions(allowed)
        or not next_code
    ):
        return _finalize_close_or_round_trip_continue_hint(
            workflow=workflow,
            tenant_schema=tenant_schema,
            booking=booking,
            shipment=shipment,
            driver=driver,
        )

    # POD compliant, unloading done, waiting for Delivered / payment / close
    if pod_compliant and not is_job_closed:
        if is_cod and not cod_collected:
            return _finalize_hint(
                _build_collect_payment_timeline_hint(
                    workflow=workflow,
                    tenant_schema=tenant_schema,
                    shipment=shipment,
                    booking=booking,
                    reason='POD verified. Tap Collect Payment on the timeline to continue.',
                    pod_submitted=pod_just_submitted,
                ),
                workflow,
            )
        if _job_close_ready_for_hint(
            pod_cod=pod_cod,
            order_type=order_type,
            is_job_closed=is_job_closed,
            shipment_status=shipment_status,
        ):
            return _finalize_close_or_round_trip_continue_hint(
                workflow=workflow,
                tenant_schema=tenant_schema,
                booking=booking,
                shipment=shipment,
                driver=driver,
            )
        return _finalize_hint(
            {
                'action': 'refresh_job_detail',
                'screen': 'job_detail',
                'reason': (
                    'POD verified. Finalising delivery status. Pull to refresh.'
                ),
                'auto_refresh_seconds': 3,
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
        )

    # Generic fallback
    hint = _finalize_hint(
        {
            'action': 'refresh_job_detail',
            'screen': 'job_detail',
            'reason': 'Pull to refresh for latest status.',
            'job_closed': False,
            'show_completion_screen': False,
        },
        workflow,
    )
    return _merge_pod_navigation_from_workflow_row(hint, workflow)
