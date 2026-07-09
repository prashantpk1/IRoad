"""
mobile_api/utils/next_action_hint_builder.py

Driver-facing next-step hints for Job Detail and Execute Action responses.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy
from mobile_api.helpers.cod_amount import build_cod_payment_display
from mobile_api.helpers.hard_copy_workflow_gate import (
    digital_evidence_complete_for_pod_cod,
    hard_copy_step_due,
    hard_copy_workflow_gate_open,
    unloading_pending_for_pod_workflow,
)
from mobile_api.helpers.job_action_resolver import (
    action_code_is_collect_payment,
    action_code_is_job_close,
    resolve_collect_payment_action_code_from_context,
    resolve_delivery_arrival_action_code_from_context,
    resolve_job_close_action_code_from_context,
    resolve_unloading_action_code_from_context,
    resolve_unloading_completed_action_code_from_context,
    row_action_reason_label,
    row_is_collect_payment_action,
    row_is_confirm_loaded_action,
    row_is_delivery_arrival_action,
    row_is_job_close_action,
    row_is_start_job_action,
    row_is_unloading_action,
    row_is_unloading_completed_action,
)
from mobile_api.helpers.empty_move_action_resolver import (
    resolve_empty_move_complete_action_code,
    row_is_empty_move_action,
)
from iroad_tenants.operation_runtime.movement_state_machine import (
    is_movement_complete_action,
)
from tenant_workspace.models import TenantShipment, TenantTruckMovementLog
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    action_code_is_digital_pod_upload,
    action_code_is_hard_copy_custody,
    resolve_digital_pod_action_code_from_context,
    resolve_hard_copy_action_code_from_context,
    row_has_digital_pod_upload,
    row_has_hard_copy_collection,
)
from mobile_api.pod_capture.services.pod_section_metadata import build_pod_capture_steps
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    shipment_at_or_past_in_transit,
    shipment_delivery_arrival_done,
    shipment_pod_prerequisites_done,
    shipment_pod_upload_log_is_valid,
    shipment_unloading_completed_done,
    shipment_unloading_done,
)


def _movement_workflow_context(
    workflow: dict[str, Any],
    *,
    movement: Any | None = None,
) -> bool:
    if movement is not None:
        return True
    metadata = dict(workflow.get('workflow_metadata') or {})
    entity_type = str(metadata.get('entity_type') or '').strip().casefold()
    job_type = str(
        metadata.get('job_type') or workflow.get('job_type') or ''
    ).strip().casefold()
    return entity_type == 'movement' or job_type == 'movement'


def _neutral_pod_cod_for_movement() -> dict[str, Any]:
    """Empty-move jobs have no POD/COD gates — avoid shipment defaults in hints."""
    return {
        'pod_pending': False,
        'pod_compliant': False,
        'hard_pod_pending': False,
        'cod_pending': False,
        'cod_collected': False,
        'treasury_pending': False,
        'delivery_blocked': False,
        'digital_evidence_complete': True,
    }


def _build_empty_move_execute_hint(
    workflow: dict[str, Any],
    *,
    action_code: str = '',
) -> dict[str, Any]:
    code = (action_code or '').strip()
    if not code:
        next_action = workflow.get('next_action') or {}
        code = str(next_action.get('action_code') or '').strip()
    row = _resolve_action_row(workflow, code)
    return _build_evidence_capture_hint(
        action_code=code,
        reason=(
            row_action_reason_label(row, code)
            or 'Capture movement evidence before continuing.'
        ),
        workflow=workflow,
        ui_mode='empty_move',
    )


def _movement_dashboard_hint() -> dict[str, Any]:
    return {
        'action': 'go_to_dashboard',
        'screen': 'dashboard',
        'reason': 'Movement complete.',
        'job_closed': True,
        'show_completion_screen': True,
    }


def _empty_move_complete_action_code(
    action_code: str | None,
    *,
    tenant_schema: str,
    workflow: dict[str, Any],
) -> bool:
    token = (action_code or '').strip().upper()
    if not token:
        return False
    complete_code = resolve_empty_move_complete_action_code(tenant_schema).strip().upper()
    if complete_code and token == complete_code:
        return True
    row = _resolve_action_row(workflow, token)
    if not row:
        return False
    action = row if not isinstance(row, dict) else SimpleNamespace(
        action_code=row.get('action_code'),
        english_label=row.get('english_label') or row.get('execution_label') or row.get('label'),
        arabic_label=row.get('arabic_label'),
        movement_status_impact=(row.get('execution_requirements') or {}).get(
            'movement_status_impact',
        )
        or row.get('movement_status_impact'),
        shipment_status_impact='',
    )
    return is_movement_complete_action(action)


def _movement_terminal_for_hint(
    movement: Any | None,
    *,
    action_code: str | None,
    tenant_schema: str,
    workflow: dict[str, Any],
) -> bool:
    if movement is not None:
        status = (getattr(movement, 'status', '') or '').strip()
        if status == TenantTruckMovementLog.Status.COMPLETED:
            return True
    if _empty_move_complete_action_code(
        action_code,
        tenant_schema=tenant_schema,
        workflow=workflow,
    ):
        return True
    steps = list(workflow.get('workflow_status') or [])
    if steps and all(bool(step.get('completed')) for step in steps):
        return True
    return False


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
    shipment: Any | None = None,
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
        'show_pod_capture_button': True,
    }
    from mobile_api.pod_capture.services.pod_section_metadata import (
        build_digital_evidence_block,
    )

    block = build_digital_evidence_block(
        shipment,
        tenant_schema=tenant_schema,
        has_hard_copy_step=hard_copy_applicable,
        allow_hard_copy_wizard_next=bool(
            dict(pod_cod.get('hard_copy_confirmation') or {}).get('applicable'),
        ),
    )
    if block.get('capture_ui'):
        hint['capture_ui'] = block['capture_ui']
    if block.get('action_code') and not hint.get('action_code'):
        hint['action_code'] = block['action_code']
    if hard_copy_applicable:
        block = dict(pod_cod.get('hard_copy_confirmation') or {})
        hint['documents_endpoint'] = block.get('documents_endpoint') or ''
        hint['custody_submit_endpoint'] = block.get('submit_endpoint') or ''
    from mobile_api.job_detail.services.job_detail_navigation_reconciler import (
        apply_pod_mobile_cta_contract,
    )

    return apply_pod_mobile_cta_contract(hint)


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
    is_cod = (getattr(shipment, 'order_type', None) or '').strip().upper() == 'COD'
    primary = dict(workflow.get('primary_action') or {})
    shipment_status = _column_shipment_status(workflow, shipment)
    if shipment is not None:
        shipment_status = (
            (getattr(shipment, 'shipment_status', None) or '').strip()
            or shipment_status
        )
    if _unloading_completed_step_due(
        shipment,
        workflow,
        shipment_status,
        tenant_schema=tenant_schema,
    ):
        return _finalize_hint(
            _build_unloading_completed_execute_hint(
                workflow,
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
    code = str(
        hint.get('action_code')
        or primary.get('action_code')
        or (workflow.get('next_action') or {}).get('action_code')
        or ''
    ).strip()
    row = _resolve_action_row(workflow, code) or primary

    if _hard_copy_step_required(pod_cod) and digital_evidence_complete_for_pod_cod(pod_cod):
        payment_hint = (
            str(hint.get('action') or '') == 'go_to_payment_collection'
            or str(hint.get('screen') or '') == 'collect_payment'
            or row_is_collect_payment_action(primary)
            or row_is_collect_payment_action(row)
            or row_is_collect_payment_action(hint)
        )
        if payment_hint:
            return _finalize_hint(
                _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
                workflow,
            )

    if is_cod and (
        row_is_collect_payment_action(primary)
        or row_is_collect_payment_action(row)
        or row_is_collect_payment_action(hint)
    ):
        if pod_cod.get('pod_pending') and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        ):
            return _finalize_hint(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                    shipment=shipment,
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
        if _hard_copy_step_required(pod_cod):
            return _finalize_hint(
                _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
                workflow,
            )
        if (
            is_cod
            and not pod_cod.get('cod_collected')
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

    if is_cod and _hard_copy_step_required(pod_cod) and (
        row_is_collect_payment_action(primary)
        or row_is_collect_payment_action(row)
        or row_is_collect_payment_action(hint)
    ):
        if _unloading_step_due(shipment, workflow):
            return _finalize_hint(
                _build_unloading_execute_hint(
                    workflow,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        return _finalize_hint(
            _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
            workflow,
        )

    if not _hard_copy_step_required(pod_cod):
        allowed = workflow.get('allowed_actions') or []
        if row_is_job_close_action(primary) or _job_close_in_allowed_actions(allowed):
            if (
                str(hint.get('action') or '') == 'go_to_pod_capture'
                and not pod_cod.get('pod_pending')
            ):
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

    if (
        pod_cod.get('pod_pending')
        and row_has_digital_pod_upload(row)
        and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        )
    ):
        if str(hint.get('action') or '') != 'go_to_pod_capture':
            return _finalize_hint(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                    shipment=shipment,
                ),
                workflow,
            )
        return _merge_pod_navigation_from_workflow_row(
            _finalize_hint(dict(hint), workflow),
            workflow,
            pod_cod=pod_cod,
        )

    if _hard_copy_step_required(pod_cod) and digital_evidence_complete_for_pod_cod(pod_cod):
        if str(hint.get('action') or '') != 'go_to_pod_capture':
            return _finalize_hint(
                _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
                workflow,
            )

    return _merge_pod_navigation_from_workflow_row(
        _finalize_hint(dict(hint), workflow),
        workflow,
        pod_cod=pod_cod,
    )


def _merge_pod_navigation_from_workflow_row(
    hint: dict[str, Any],
    workflow: dict[str, Any],
    *,
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy POD wizard contract from primary/next action when already projected."""
    code = str(hint.get('action_code') or '').strip()
    primary = dict(workflow.get('primary_action') or {})
    if not code:
        if str(hint.get('action') or '') != 'go_to_pod_capture':
            return hint
        row = primary
        if not row or str(row.get('action') or '') != 'go_to_pod_capture':
            return hint
    else:
        row = _resolve_action_row(workflow, code) or primary
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
    from mobile_api.helpers.hard_copy_workflow_gate import (
        coerce_digital_pod_capture_row,
        hard_copy_step_due,
    )

    if not hard_copy_step_due(pod_cod):
        return coerce_digital_pod_capture_row(out, pod_cod=pod_cod)
    return out


def _is_digital_pod_next(
    workflow: dict[str, Any],
    next_code: str,
    *,
    tenant_schema: str = '',
) -> bool:
    if not (next_code or '').strip():
        return False
    row = _resolve_action_row(workflow, next_code)
    if row_has_digital_pod_upload(row):
        return True
    resolved = resolve_digital_pod_action_code_from_context(
        workflow=workflow,
        tenant_schema=tenant_schema,
    )
    if resolved and (next_code or '').strip().casefold() == resolved.casefold():
        return True
    return action_code_is_digital_pod_upload(
        next_code,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )


def _is_hard_copy_pod_next(
    workflow: dict[str, Any],
    next_code: str,
    *,
    tenant_schema: str = '',
) -> bool:
    row = _resolve_action_row(workflow, next_code)
    if row_has_hard_copy_collection(row):
        return True
    return action_code_is_hard_copy_custody(
        next_code,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )


def _unloading_completed_execute_just_completed(
    action_code: str | None,
    workflow: dict[str, Any],
    *,
    tenant_schema: str = '',
) -> bool:
    code = (action_code or '').strip()
    if not code:
        return False
    row = _resolve_action_row(workflow, code)
    if row_is_unloading_completed_action(row):
        return True
    resolved = resolve_unloading_completed_action_code_from_context(
        workflow=workflow,
        tenant_schema=tenant_schema,
    )
    return bool(resolved) and code.casefold() == resolved.casefold()


def _executed_digital_pod_upload(
    workflow: dict[str, Any],
    action_code: str | None,
    *,
    tenant_schema: str = '',
) -> bool:
    row = _resolve_action_row(workflow, action_code or '')
    if row_is_unloading_completed_action(row):
        return False
    if row_has_digital_pod_upload(row) and not row_has_hard_copy_collection(row):
        return True
    return action_code_is_digital_pod_upload(
        action_code,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )


def _hard_copy_custody_execute_just_completed(
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    action_code: str | None,
    *,
    tenant_schema: str = '',
) -> bool:
    """True on execute response immediately after hard-copy custody promotion."""
    if not (action_code or '').strip():
        return False
    if pod_cod.get('hard_pod_pending'):
        return False
    if not digital_evidence_complete_for_pod_cod(pod_cod):
        return False
    promoted = action_code_is_hard_copy_custody(
        action_code,
        workflow=workflow,
        tenant_schema=tenant_schema,
    )
    if not promoted:
        promoted = action_code_is_digital_pod_upload(
            action_code,
            workflow=workflow,
            tenant_schema=tenant_schema,
        )
    if not promoted:
        return False
    return bool(pod_cod.get('pod_compliant'))


def _pod_execute_just_completed(
    workflow: dict[str, Any],
    pod_cod: dict[str, Any],
    action_code: str | None,
    *,
    tenant_schema: str = '',
) -> bool:
    """True only on the execute-action response immediately after digital POD."""
    if not (action_code or '').strip():
        return False
    if not _executed_digital_pod_upload(
        workflow,
        action_code,
        tenant_schema=tenant_schema,
    ):
        return False
    if _hard_copy_step_required(pod_cod):
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
    return hard_copy_step_due(pod_cod)


def _pod_upload_step_due(
    shipment: Any | None,
    pod_cod: dict[str, Any],
    workflow: dict[str, Any],
    *,
    tenant_schema: str = '',
) -> bool:
    """Digital POD capture after unloading milestones when no valid POD log exists."""
    if unloading_pending_for_pod_workflow(pod_cod):
        return False
    if digital_evidence_complete_for_pod_cod(pod_cod) and not pod_cod.get(
        'hard_pod_pending',
        False,
    ) and not pod_cod.get('pod_pending', False):
        return False
    if shipment is None:
        return bool(pod_cod.get('pod_pending') or pod_cod.get('hard_pod_pending'))
    if not shipment_pod_prerequisites_done(shipment):
        return False
    if not shipment_unloading_completed_done(shipment):
        return False
    if shipment_pod_upload_log_is_valid(shipment):
        return False
    allowed = workflow.get('allowed_actions') or []
    has_pod_step = any(
        isinstance(row, dict) and row_has_digital_pod_upload(row)
        for row in allowed
    )
    if not has_pod_step and not resolve_digital_pod_action_code_from_context(
        pod_cod=pod_cod,
        workflow=workflow,
        tenant_schema=tenant_schema,
    ):
        return False
    return True


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


def resolve_round_trip_continuation_open_job(
    booking: Any | None,
    *,
    driver: Any | None = None,
) -> dict[str, Any] | None:
    """
    Canonical job pointer after outbound completes (booking bootstrap or active leg).
    """
    open_job = _resolve_round_trip_return_open_job(booking, driver=driver)
    if open_job:
        return open_job
    if booking is None:
        return None
    from mobile_api.job_detail.helpers.booking_job_context import load_booking_shipments

    shipments = load_booking_shipments(booking)
    active = booking_policy.get_active_shipment_for_driver(driver, booking, shipments)
    if active is None:
        return None
    if driver is not None and not booking_policy.driver_owns_shipment_leg(
        driver,
        booking,
        active,
    ):
        return None
    line = str(getattr(active, 'booking_item_type', '') or '').strip()
    if line.casefold() not in {'backload', 'inbound'}:
        return None
    ship_id = getattr(active, 'shipment_id', None) or getattr(active, 'pk', None)
    return {
        'job_type': 'shipment',
        'job_id': str(ship_id) if ship_id is not None else '',
        'job_no': str(getattr(active, 'shipment_no', '') or ''),
        'booking_item_type': line or 'Backload',
    }


def _leg_complete_navigation_hint(
    open_job: dict[str, Any] | None,
    *,
    reason: str,
) -> dict[str, Any]:
    """Navigate to return leg — replaces stale outbound shipment on back press."""
    hint: dict[str, Any] = {
        'action': 'navigate_open_job',
        'screen': 'job_detail',
        'job_closed': False,
        'show_completion_screen': True,
        'leg_completed': True,
        'booking_continues': True,
        'reason': reason,
        'replace_navigation_stack': True,
    }
    if open_job:
        hint['open_job'] = open_job
        hint['job_type'] = open_job.get('job_type', '')
        hint['job_id'] = open_job.get('job_id', '')
    return hint


def _round_trip_leg_complete_continue_hint(
    booking: Any | None,
    *,
    driver: Any | None = None,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Outbound leg finished — continue return trip instead of Job Close."""
    open_job = resolve_round_trip_continuation_open_job(booking, driver=driver)
    if open_job:
        return _leg_complete_navigation_hint(
            open_job,
            reason=(
                'Outbound trip complete. Continue the return trip from this job.'
            ),
        )
    return {
        'action': 'go_to_dashboard',
        'screen': 'dashboard',
        'job_closed': False,
        'show_completion_screen': True,
        'leg_completed': True,
        'booking_continues': True,
        'reason': 'Outbound leg complete. Continue the return trip from My Jobs.',
    }


def _finalize_job_close_timeline_hint(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
    payment_collected: bool = False,
    booking: Any | None = None,
    shipment: Any | None = None,
) -> dict[str, Any]:
    """Stay on job detail; driver closes the job from the timeline row."""
    from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy

    workflow = dict(workflow or {})
    hint = dict(_close_job_hint(workflow=workflow, tenant_schema=tenant_schema))
    is_round_outbound = (
        booking is not None
        and shipment is not None
        and booking_policy._is_outbound_line_type(shipment)
        and booking_policy.normalized_trip_type(booking).casefold() == 'round'
    )
    if is_round_outbound:
        hint['reason'] = (
            'All steps complete. Tap End Job to finish round 1, '
            'then start the return trip.'
        )
    elif payment_collected:
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
    if payment_collected and is_round_outbound:
        hint.update(
            {
                'reason': (
                    'Payment collected successfully. Tap End Job to finish round 1, '
                    'then start the return trip.'
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
    from mobile_api.dashboard.selectors import booking_selection_policy as booking_policy

    if (
        booking is not None
        and shipment is not None
        and booking_policy.round_trip_defers_job_close(booking, shipment)
    ):
        return _finalize_hint(
            _round_trip_leg_complete_continue_hint(
                booking,
                driver=driver,
                workflow=workflow,
            ),
            workflow,
        )
    return _finalize_job_close_timeline_hint(
        workflow=workflow,
        tenant_schema=tenant_schema,
        payment_collected=payment_collected,
        booking=booking,
        shipment=shipment,
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
    if photo_min >= 1:
        return True
    if capture_mode in {'photo_evidence', 'loading_photos'}:
        return True
    return False


def _finalize_hint(
    hint: dict[str, Any],
    workflow: dict[str, Any],
    *,
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach driver-facing flags derived from workflow execution_requirements."""
    out = dict(hint)
    if pod_cod is not None and str(out.get('action') or '') == 'go_to_pod_capture':
        from mobile_api.helpers.hard_copy_workflow_gate import coerce_digital_pod_capture_row

        out = coerce_digital_pod_capture_row(out, pod_cod=pod_cod)
    action = str(out.get('action') or '')
    code = str(out.get('action_code') or '').strip()
    if action == 'execute_action_with_media':
        out['requires_multipart'] = True
    elif action in {'execute_action', 'go_to_evidence_capture'} and code:
        row = _resolve_action_row(workflow, code)
        out['requires_multipart'] = _requires_multipart_for_action(
            row,
            capture_mode=str(out.get('capture_mode') or ''),
        )
    else:
        out['requires_multipart'] = False
    return out


def _build_evidence_capture_hint(
    *,
    action_code: str,
    reason: str = '',
    ui_mode: str = '',
    screen_title: str = '',
    show_close_job_button: bool = False,
    payment_collected: bool = False,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from mobile_api.execution.evidence.constants import (
        POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
    )
    from mobile_api.execution.evidence.evidence_capture_ui import (
        build_generic_evidence_capture_ui,
    )
    from mobile_api.helpers.evidence_requirement_flags import (
        normalize_evidence_requirements,
        sync_row_evidence_flags,
    )

    row = _resolve_action_row(workflow or {}, action_code) if action_code else {}
    base_requirements = {
        'gps': True,
        'photo_enabled': True,
        'video_enabled': True,
        'photo_min_count': 0,
        'video_min_count': 0,
        'video_max_count': 1,
        'video_max_duration_seconds': POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
        'note': False,
        'note_required': False,
        'requires_evidence_capture': True,
        'capture_mode': 'optional_evidence',
    }
    base_requirements.update(dict(row.get('execution_requirements') or {}))
    requirements = normalize_evidence_requirements(base_requirements)
    title = (
        (screen_title or '').strip()
        or str(
            row.get('execution_label')
            or row.get('action_name')
            or row.get('english_label')
            or row.get('label')
            or '',
        ).strip()
        or 'Capturing Action Evidences'
    )
    capture_ui = build_generic_evidence_capture_ui(
        requirements,
        action_code=action_code,
        screen_title=title,
    )
    hint: dict[str, Any] = {
        'action': 'go_to_evidence_capture',
        'screen': 'evidence_capture',
        'action_code': action_code,
        'direct_execute': False,
        'requires_evidence_capture': True,
        'reason': reason,
        'job_closed': False,
        'show_completion_screen': False,
        'screen_title': title,
        'execution_requirements': requirements,
        'capture_ui': capture_ui,
        'photo_min_count': int(requirements.get('photo_min_count') or 0),
        'video_min_count': int(requirements.get('video_min_count') or 0),
    }
    if ui_mode:
        hint['ui_mode'] = ui_mode
    if show_close_job_button:
        hint['show_close_job_button'] = True
    if payment_collected:
        hint['payment_collected'] = True
    return sync_row_evidence_flags(hint)


def _close_job_hint(
    *,
    workflow: dict[str, Any] | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    return _build_evidence_capture_hint(
        action_code=resolve_job_close_action_code_from_context(
            workflow=workflow,
            tenant_schema=tenant_schema,
        ),
        reason='All steps complete. Tap Job Close to finish this leg.',
        ui_mode='job_close',
        screen_title='Job Close',
        show_close_job_button=True,
        workflow=workflow,
    )


def _job_close_in_allowed_actions(allowed: list[Any]) -> bool:
    for row in allowed:
        if isinstance(row, dict) and row_is_job_close_action(row):
            return True
    return False


def _is_collect_payment_next(workflow: dict[str, Any], next_code: str) -> bool:
    return row_is_collect_payment_action(_resolve_action_row(workflow, next_code))


def _is_delivery_arrival_next(workflow: dict[str, Any], next_code: str) -> bool:
    return row_is_delivery_arrival_action(_resolve_action_row(workflow, next_code))


def _workflow_has_step(
    workflow: dict[str, Any],
    predicate,
    *,
    tenant_schema: str = '',
    resolve_code,
) -> bool:
    for row in workflow.get('allowed_actions') or []:
        if isinstance(row, dict) and predicate(row):
            return True
    for key in ('next_action', 'primary_action'):
        row = workflow.get(key) or {}
        if isinstance(row, dict) and predicate(row):
            return True
    if workflow.get('allowed_actions'):
        return False
    return bool((resolve_code(workflow=workflow, tenant_schema=tenant_schema) or '').strip())


def _delivery_arrival_step_due(
    shipment: Any | None,
    workflow: dict[str, Any],
    shipment_status: str = '',
    *,
    tenant_schema: str = '',
) -> bool:
    if shipment is None:
        return False
    if shipment_delivery_arrival_done(shipment):
        return False
    status = (
        (shipment_status or '').strip()
        or (getattr(shipment, 'shipment_status', None) or '').strip()
    )
    if status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }:
        return False
    if not shipment_at_or_past_in_transit(shipment):
        return False
    return _workflow_has_step(
        workflow,
        row_is_delivery_arrival_action,
        tenant_schema=tenant_schema,
        resolve_code=resolve_delivery_arrival_action_code_from_context,
    )


def _build_delivery_arrival_execute_hint(
    workflow: dict[str, Any],
    *,
    tenant_schema: str = '',
    action_code: str = '',
) -> dict[str, Any]:
    code = (
        (action_code or '').strip()
        or resolve_delivery_arrival_action_code_from_context(
            workflow=workflow,
            tenant_schema=tenant_schema,
        )
    )
    return _build_evidence_capture_hint(
        action_code=code,
        reason='Confirm arrival at the delivery site.',
        workflow=workflow,
    )


def _is_unloading_next(workflow: dict[str, Any], next_code: str) -> bool:
    return row_is_unloading_action(_resolve_action_row(workflow, next_code))


def _unloading_step_due(
    shipment: Any | None,
    workflow: dict[str, Any],
    shipment_status: str = '',
    *,
    tenant_schema: str = '',
) -> bool:
    if shipment is None:
        return False
    if shipment_unloading_done(shipment):
        return False
    status = (
        (shipment_status or '').strip()
        or (getattr(shipment, 'shipment_status', None) or '').strip()
    )
    if status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }:
        return False
    at_delivery_site = (
        shipment_delivery_arrival_done(shipment)
        or status
        in {
            TenantShipment.ShipmentStatus.AT_DELIVERY,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
            TenantShipment.ShipmentStatus.DELIVERED,
        }
    )
    if not at_delivery_site:
        return False
    if not shipment_at_or_past_in_transit(shipment):
        return False
    return _workflow_has_step(
        workflow,
        row_is_unloading_action,
        tenant_schema=tenant_schema,
        resolve_code=resolve_unloading_action_code_from_context,
    )


def _unloading_completed_step_due(
    shipment: Any | None,
    workflow: dict[str, Any],
    shipment_status: str = '',
    *,
    tenant_schema: str = '',
) -> bool:
    if shipment is None:
        return False
    if shipment_unloading_completed_done(shipment):
        return False
    if not shipment_delivery_arrival_done(shipment):
        return False
    if not shipment_unloading_done(shipment):
        return False
    status = (
        (shipment_status or '').strip()
        or (getattr(shipment, 'shipment_status', None) or '').strip()
    )
    if status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }:
        return False
    if not shipment_at_or_past_in_transit(shipment):
        return False
    return _workflow_has_step(
        workflow,
        row_is_unloading_completed_action,
        tenant_schema=tenant_schema,
        resolve_code=resolve_unloading_completed_action_code_from_context,
    )


def _build_unloading_completed_execute_hint(
    workflow: dict[str, Any],
    *,
    tenant_schema: str = '',
    action_code: str = '',
) -> dict[str, Any]:
    code = (action_code or '').strip()
    if not code:
        code = resolve_unloading_completed_action_code_from_context(
            workflow=workflow,
            tenant_schema=tenant_schema,
        )
    return _build_evidence_capture_hint(
        action_code=code,
        reason='Confirm unloading is complete.',
        workflow=workflow,
    )


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
    return _build_evidence_capture_hint(
        action_code=code,
        reason='Confirm start unloading at delivery site.',
        workflow=workflow,
    )


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
    movement: Any | None = None,
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
    movement_job = _movement_workflow_context(workflow, movement=movement)
    if movement_job and not pod_cod:
        pod_cod = _neutral_pod_cod_for_movement()
    else:
        pod_cod = pod_cod or {}

    def _fin(hint: dict[str, Any]) -> dict[str, Any]:
        return _finalize_hint(hint, workflow, pod_cod=pod_cod)

    if movement is not None:
        if _movement_terminal_for_hint(
            movement,
            action_code=action_code,
            tenant_schema=tenant_schema,
            workflow=workflow,
        ):
            return _finalize_hint(_movement_dashboard_hint(), workflow)

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

    if movement_job and next_code:
        next_row = _resolve_action_row(workflow, next_code)
        if row_is_empty_move_action(next_row) or movement is not None:
            return _finalize_hint(
                _build_empty_move_execute_hint(
                    workflow,
                    action_code=next_code,
                ),
                workflow,
            )

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
    pod_just_submitted = _pod_execute_just_completed(
        workflow,
        pod_cod,
        action_code,
        tenant_schema=tenant_schema,
    )
    payment_just_collected = _collect_payment_execute_just_completed(
        workflow,
        pod_cod,
        action_code,
    )

    if workflow.get('backload_bootstrap_pending') and shipment is None and booking is not None and allowed:
        open_job = _resolve_round_trip_return_open_job(booking, driver=driver)
        row = _resolve_action_row(workflow, next_code)
        label = row_action_reason_label(row, next_code) if row else 'Start the return trip.'
        hint: dict[str, Any] = {
            'action': 'refresh_job_detail',
            'screen': 'job_detail',
            'action_code': next_code,
            'reason': label or 'Outbound leg complete. Start the return trip.',
            'job_closed': False,
            'show_completion_screen': False,
            'leg_completed': True,
            'booking_continues': True,
        }
        if open_job:
            hint['open_job'] = open_job
        return _finalize_hint(hint, workflow)

    # TERMINAL STATE — shipment column Closed (Delivered still needs job close)
    if is_job_closed or action_code_is_job_close(
        action_code,
        workflow=workflow,
        tenant_schema=tenant_schema,
    ):
        open_job = resolve_round_trip_continuation_open_job(booking, driver=driver)
        booking_continues = bool(open_job)
        if open_job:
            return _finalize_hint(
                _leg_complete_navigation_hint(
                    open_job,
                    reason=(
                        'Outbound trip complete. Continue the return trip from this job.'
                    ),
                ),
                workflow,
            )
        hint: dict[str, Any] = {
            'action': 'go_to_dashboard',
            'screen': 'dashboard',
            'job_closed': not booking_continues,
            'show_completion_screen': True,
            'reason': 'Job is complete. No more actions required.',
        }
        return _finalize_hint(hint, workflow)

    # Job close / round-trip handoff — after POD+COD gates, before delivery milestones.
    if (
        next_code
        and row_is_job_close_action(_resolve_action_row(workflow, next_code))
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

    # Delivery Arrival — first step at the delivery site after In Transit.
    if _delivery_arrival_step_due(
        shipment,
        workflow,
        shipment_status,
        tenant_schema=tenant_schema,
    ):
        return _finalize_hint(
            _build_delivery_arrival_execute_hint(
                workflow,
                tenant_schema=tenant_schema,
            ),
            workflow,
        )

    # Start Unloading at delivery — before POD upload, hard copy, and COD collection.
    if _unloading_step_due(
        shipment,
        workflow,
        shipment_status,
        tenant_schema=tenant_schema,
    ):
        return _finalize_hint(
            _build_unloading_execute_hint(
                workflow,
                tenant_schema=tenant_schema,
            ),
            workflow,
        )

    # Unloading Completed — after Start Unloading, before POD / payment / close.
    if _unloading_completed_step_due(
        shipment,
        workflow,
        shipment_status,
        tenant_schema=tenant_schema,
    ):
        return _finalize_hint(
            _build_unloading_completed_execute_hint(
                workflow,
                tenant_schema=tenant_schema,
            ),
            workflow,
        )

    # Execute response immediately after Unloading Completed → digital POD (never hard copy).
    if _unloading_completed_execute_just_completed(
        action_code,
        workflow,
        tenant_schema=tenant_schema,
    ) and _pod_upload_step_due(
        shipment,
        pod_cod,
        workflow,
        tenant_schema=tenant_schema,
    ):
        return _fin(
            _build_digital_pod_capture_hint(
                workflow,
                pod_cod,
                tenant_schema=tenant_schema,
                shipment=shipment,
            ),
        )

    # Upload POD — after delivery arrival + unloading (ignores out-of-order POD logs).
    if _pod_upload_step_due(
        shipment,
        pod_cod,
        workflow,
        tenant_schema=tenant_schema,
    ):
        return _fin(
            _build_digital_pod_capture_hint(
                workflow,
                pod_cod,
                tenant_schema=tenant_schema,
                shipment=shipment,
            ),
        )

    # Digital POD step 1 — before hard-copy confirmation on HARD jobs.
    if not digital_evidence_complete_for_pod_cod(pod_cod):
        digital_due = pod_pending or hard_pod_pending
        if digital_due and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        ):
            return _fin(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                    shipment=shipment,
                ),
            )

    # Hard copy custody still due — Upload POD step 2 after digital POD + portal document.
    if _hard_copy_step_required(pod_cod) and digital_evidence_complete_for_pod_cod(pod_cod):
        return _finalize_hint(
            _hard_copy_hint(
                workflow,
                pod_cod,
                tenant_schema=tenant_schema,
            ),
            workflow,
            pod_cod=pod_cod,
        )

    # Hard copy custody just completed — Collect Payment (COD only) or Job Close.
    if _hard_copy_custody_execute_just_completed(
        workflow,
        pod_cod,
        action_code,
        tenant_schema=tenant_schema,
    ):
        if is_cod and not cod_collected and not treasury_pending:
            return _finalize_hint(
                _build_collect_payment_timeline_hint(
                    workflow=workflow,
                    tenant_schema=tenant_schema,
                    shipment=shipment,
                    booking=booking,
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

    # Digital POD logged but portal Shipment Document missing — do not open hard copy.
    if (
        digital_evidence_complete_for_pod_cod(pod_cod)
        and bool(pod_cod.get('hard_pod_pending') or _hard_copy_applicable(pod_cod))
        and not _hard_copy_step_required(pod_cod)
    ):
        message = (pod_cod.get('shipment_document_message') or '').strip()
        if not message:
            from iroad_tenants.operation_runtime.pod_action import (
                POD_REQUIRES_SHIPMENT_DOCUMENT_MSG,
            )

            message = POD_REQUIRES_SHIPMENT_DOCUMENT_MSG
        return _finalize_hint(
            {
                'action': 'refresh_job_detail',
                'screen': 'job_detail',
                'reason': message,
                'shipment_document_required': True,
                'shipment_document_ready': False,
                'shipment_document_message': message,
                'job_closed': False,
                'show_completion_screen': False,
            },
            workflow,
            pod_cod=pod_cod,
        )

    # Digital POD upload is next — open evidence capture wizard step 1.
    if (
        pod_pending
        and _is_digital_pod_next(workflow, next_code, tenant_schema=tenant_schema)
        and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        )
    ):
        return _finalize_hint(
            _build_digital_pod_capture_hint(
                workflow,
                pod_cod,
                tenant_schema=tenant_schema,
                shipment=shipment,
            ),
            workflow,
        )

    next_row = _resolve_action_row(workflow, next_code) if next_code else {}

    # Start job — optional evidence screen (tenant-specific OA code).
    if next_code and row_is_start_job_action(next_row):
        return _finalize_hint(
            _build_evidence_capture_hint(
                action_code=next_code,
                reason=row_action_reason_label(next_row, next_code),
                workflow=workflow,
            ),
            workflow,
        )

    # Start Unloading — GPS-only confirm at delivery site (tenant-specific code).
    if _is_delivery_arrival_next(workflow, next_code):
        return _finalize_hint(
            _build_delivery_arrival_execute_hint(
                workflow,
                tenant_schema=tenant_schema,
                action_code=next_code,
            ),
            workflow,
        )

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

    # COD payment collection is next — only for COD orders after POD / hard-copy gates.
    if is_cod and _is_collect_payment_next(workflow, next_code):
        if pod_pending and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        ):
            if _is_digital_pod_next(workflow, next_code, tenant_schema=tenant_schema) or any(
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
        if _hard_copy_step_required(pod_cod) and digital_evidence_complete_for_pod_cod(
            pod_cod,
        ):
            return _finalize_hint(
                _hard_copy_hint(workflow, pod_cod, tenant_schema=tenant_schema),
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
            _build_evidence_capture_hint(
                action_code=next_code,
                reason=(
                    row_action_reason_label(next_row, next_code)
                    or 'Confirm cargo is loaded.'
                ),
                workflow=workflow,
            ),
            workflow,
        )

    # Normal next action available
    if next_code and allowed:
        row = _resolve_action_row(workflow, next_code)
        premature_pod = row_has_digital_pod_upload(row) and not _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        )
        if not premature_pod:
            if (
                pod_pending
                and _pod_upload_step_due(
                    shipment,
                    pod_cod,
                    workflow,
                    tenant_schema=tenant_schema,
                )
                and (
                    row_has_digital_pod_upload(row)
                    or (
                        resolve_digital_pod_action_code_from_context(
                            pod_cod=pod_cod,
                            workflow=workflow,
                            tenant_schema=tenant_schema,
                        )
                        == next_code
                    )
                )
            ):
                return _finalize_hint(
                    _build_digital_pod_capture_hint(
                        workflow,
                        pod_cod,
                        tenant_schema=tenant_schema,
                        shipment=shipment,
                    ),
                    workflow,
                )
            label = row_action_reason_label(row, next_code)
            return _finalize_hint(
                _build_evidence_capture_hint(
                    action_code=next_code,
                    reason=label,
                    workflow=workflow,
                ),
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
        if pod_pending and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        ):
            return _finalize_hint(
                _build_digital_pod_capture_hint(
                    workflow,
                    pod_cod,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        if _delivery_arrival_step_due(
            shipment,
            workflow,
            shipment_status,
            tenant_schema=tenant_schema,
        ):
            return _finalize_hint(
                _build_delivery_arrival_execute_hint(
                    workflow,
                    tenant_schema=tenant_schema,
                ),
                workflow,
            )
        if _unloading_step_due(shipment, workflow, shipment_status, tenant_schema=tenant_schema):
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
    if (
        shipment is not None
        and _pod_upload_step_due(
            shipment,
            pod_cod,
            workflow,
            tenant_schema=tenant_schema,
        )
    ):
        pod_code = resolve_digital_pod_action_code_from_context(
            pod_cod=pod_cod,
            workflow=workflow,
            tenant_schema=tenant_schema,
        )
        if pod_code:
            return _merge_pod_navigation_from_workflow_row(
                _finalize_hint(
                    _build_digital_pod_capture_hint(
                        workflow,
                        pod_cod,
                        tenant_schema=tenant_schema,
                        shipment=shipment,
                    ),
                    workflow,
                ),
                workflow,
                pod_cod=pod_cod,
            )

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
    return _merge_pod_navigation_from_workflow_row(hint, workflow, pod_cod=pod_cod)
