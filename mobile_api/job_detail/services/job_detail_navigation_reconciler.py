"""
Align Job Detail bottom CTA with pending timeline rows when workflow/hint lag.

Mobile reads ``next_action_hint`` (and ``workflow.primary_action``) for the
sticky action button. Timeline rows are enriched earlier with POD navigation;
when the hint engine returns ``refresh_job_detail`` without an ``action_code``,
drivers see POD helper text but no button.
"""
from __future__ import annotations

from typing import Any, Callable

from mobile_api.helpers.action_navigation_metadata import (
    _ensure_pod_row_capture_ui,
    _action_like_from_row,
    enrich_timeline_event_navigation,
)
from mobile_api.helpers.job_action_resolver import row_is_job_close_action
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    row_has_digital_pod_upload,
)


def _normalize_timeline_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map timeline event keys onto allowed-action label fields for matchers."""
    out = dict(row)
    label = str(
        out.get('action_label')
        or out.get('action_name')
        or out.get('execution_label')
        or out.get('english_label')
        or out.get('label')
        or '',
    ).strip()
    if label:
        for key in ('action_label', 'action_name', 'execution_label', 'english_label'):
            if not out.get(key):
                out[key] = label
    return out


def _first_pending_timeline_row(
    preview: list[Any] | None,
    *,
    matcher: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    for row in preview or []:
        if not isinstance(row, dict):
            continue
        if row.get('is_performed') or str(row.get('timeline_state') or '') == 'performed':
            continue
        normalized = _normalize_timeline_row(row)
        if matcher is None or matcher(normalized):
            pending.append(normalized)
    if not pending:
        return {}
    pending.sort(
        key=lambda item: (
            int(item.get('sequence_number') or 0),
            str(item.get('log_date') or item.get('created_at') or ''),
        ),
    )
    return dict(pending[0])


def _row_is_pending_pod_capture(row: dict[str, Any]) -> bool:
    if str(row.get('action') or '') == 'go_to_pod_capture':
        return True
    return row_has_digital_pod_upload(row)


def _workflow_primary_lags_pod_hint(
    workflow: dict[str, Any],
    hint: dict[str, Any],
) -> bool:
    """True when hint targets POD capture but workflow CTA still shows evidence/execute."""
    if str(hint.get('action') or '').strip() != 'go_to_pod_capture' and not hint.get(
        'show_pod_capture_button',
    ):
        return False
    primary = dict((workflow or {}).get('primary_action') or {})
    if not primary:
        return True
    if str(primary.get('action') or '').strip() != 'go_to_pod_capture':
        return True
    if str(primary.get('screen') or '').strip() == 'evidence_capture':
        return True
    if primary.get('requires_evidence_capture'):
        return True
    if not primary.get('capture_ui') and hint.get('capture_ui'):
        return True
    hint_code = str(hint.get('action_code') or '').strip()
    primary_code = str(primary.get('action_code') or '').strip()
    if hint_code and primary_code and hint_code != primary_code:
        return True
    return False


def _workflow_row_from_pod_hint(hint: dict[str, Any]) -> dict[str, Any]:
    """Build a workflow CTA row from an aligned ``next_action_hint`` POD contract."""
    row: dict[str, Any] = {}
    for key in (
        'action',
        'screen',
        'action_code',
        'capture_mode',
        'active_step',
        'ui_mode',
        'screen_title',
        'pod_capture_steps',
        'hard_pod',
        'includes_hard_copy',
        'capture_ui',
        'reason',
        'direct_execute',
        'hard_copy_confirmation',
        'confirmation_ui',
    ):
        if hint.get(key) not in (None, '', []):
            row[key] = hint[key]
    label = str(
        hint.get('action_label')
        or hint.get('button_label')
        or 'POD',
    ).strip()
    row.setdefault('action_label', label)
    row.setdefault('english_label', label)
    row.setdefault('action_name', label)
    row.setdefault('execution_label', label)
    row['show_pod_capture_button'] = True
    row.pop('requires_evidence_capture', None)
    return row


def _hint_needs_pod_cta(
    hint: dict[str, Any],
    *,
    pod_row: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
) -> bool:
    hint_action = str(hint.get('action') or '').strip()
    if pod_row:
        if hint_action != 'go_to_pod_capture':
            return True
        if workflow and _workflow_primary_lags_pod_hint(workflow, hint):
            return True
        if not hint.get('capture_ui') or not hint.get('show_pod_capture_button'):
            return True
        pod_code = str(pod_row.get('action_code') or '').strip()
        hint_code = str(hint.get('action_code') or '').strip()
        if pod_code and pod_code != hint_code:
            return True
        return False
    if hint_action in {'', 'refresh_job_detail'}:
        return True
    if not hint.get('action_code'):
        return True
    if hint_action == 'go_to_pod_capture' and not hint.get('capture_ui'):
        return True
    if hint_action == 'go_to_pod_capture' and not hint.get('show_pod_capture_button'):
        return True
    if hint_action in {'go_to_evidence_capture', 'execute_action'}:
        return True
    return False


def apply_pod_mobile_cta_contract(hint: dict[str, Any]) -> dict[str, Any]:
    """
    Mobile sticky CTA for label-only POD (``auto_pod_post`` off).

    Drivers must see the capture button when ``action`` is ``go_to_pod_capture``
    even when Operation Action Master has no auto_pod_post flag.
    """
    out = dict(hint or {})
    action = str(out.get('action') or '').strip()
    if action != 'go_to_pod_capture' and not out.get('show_pod_capture_button'):
        return out
    out['action'] = 'go_to_pod_capture'
    out['screen'] = out.get('screen') or 'pod_capture'
    out['show_pod_capture_button'] = True
    out['ready_for_pod'] = True
    out['needs_pod_capture'] = True
    code = str(
        out.get('action_code')
        or out.get('execute_action_code')
        or (out.get('capture_ui') or {}).get('primary_button', {}).get(
            'execute_action_code',
        )
        or '',
    ).strip()
    if code:
        out['action_code'] = code
        out['execute_action_code'] = code
    capture_ui = dict(out.get('capture_ui') or {})
    button = dict(capture_ui.get('primary_button') or {})
    sticky_label = _resolve_sticky_cta_button_label(out)
    if sticky_label:
        out['button_label'] = sticky_label
        out.setdefault('execution_label', sticky_label)
    elif button.get('label'):
        out.setdefault('button_label', button['label'])
    elif out.get('action_label'):
        out.setdefault('button_label', out['action_label'])
    return out


def _enrich_pending_workflow_row(
    row: dict[str, Any],
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
    timeline_preview: list[Any] | None = None,
) -> dict[str, Any]:
    """Ensure pending timeline rows expose full mobile navigation (POD capture_ui)."""
    normalized = _normalize_timeline_row(row)
    action = _action_like_from_row(normalized)
    enriched = enrich_timeline_event_navigation(
        normalized,
        action,
        shipment=shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
        timeline_preview=timeline_preview,
    )
    if _row_is_pending_pod_capture(enriched) and not enriched.get('capture_ui'):
        enriched = _ensure_pod_row_capture_ui(
            enriched,
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            has_hard_copy_step=bool(enriched.get('hard_pod')),
        )
    return enriched


def _prior_timeline_steps_performed(
    preview: list[Any] | None,
    *,
    target_row: dict[str, Any],
) -> bool:
    """True when every workflow step before ``target_row`` is already performed."""
    target_seq = int(target_row.get('sequence_number') or 0)
    if target_seq <= 1:
        return True
    for row in preview or []:
        if not isinstance(row, dict):
            continue
        seq = int(row.get('sequence_number') or 0)
        if seq <= 0 or seq >= target_seq:
            continue
        if not row.get('is_performed') and str(row.get('timeline_state') or '') != 'performed':
            return False
    return True


def _hint_covers_earlier_pending_step(
    hint: dict[str, Any],
    preview: list[Any] | None,
    *,
    before_sequence: int,
) -> bool:
    """Hint already targets a pending step that must run before POD."""
    hint_code = str(hint.get('action_code') or '').strip()
    hint_action = str(hint.get('action') or '').strip()
    if not hint_code or hint_action in {'', 'refresh_job_detail'}:
        return False
    for row in preview or []:
        if not isinstance(row, dict):
            continue
        if str(row.get('action_code') or '').strip() != hint_code:
            continue
        seq = int(row.get('sequence_number') or 0)
        if seq <= 0 or seq >= before_sequence:
            return False
        if row.get('is_performed') or str(row.get('timeline_state') or '') == 'performed':
            return False
        return True
    return False


def _timeline_row(
    *,
    seq: int,
    code: str,
    label: str,
    performed: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        'action_code': code,
        'action_label': label,
        'sequence_number': seq,
        'timeline_state': 'performed' if performed else 'pending',
        'is_performed': performed,
    }
    row.update(extra)
    return row


def _timeline_through_unloading_completed() -> list[dict[str, Any]]:
    """Performed milestones through unloading — POD is the true next step."""
    return [
        _timeline_row(seq=1, code='OA-0001', label='Start Job', performed=True),
        _timeline_row(seq=2, code='OA-0002', label='Pickup Arrival', performed=True),
        _timeline_row(seq=3, code='OA-0003', label='Start Loading', performed=True),
        _timeline_row(seq=4, code='OA-0004', label='Loading Completed', performed=True),
        _timeline_row(seq=5, code='OA-0005', label='Departure', performed=True),
        _timeline_row(seq=6, code='OA-0006', label='Delivery Arrival', performed=True),
        _timeline_row(seq=7, code='OA-0007', label='Start Unloading', performed=True),
        _timeline_row(seq=8, code='OA-0008', label='Unloading Completed', performed=True),
        _timeline_row(seq=9, code='OA-0009', label='POD', performed=False),
        _timeline_row(seq=11, code='OA-0011', label='End Job', performed=False),
    ]


_TAPPABLE_CTA_ACTIONS = frozenset(
    {
        'go_to_evidence_capture',
        'go_to_pod_capture',
        'go_to_payment_collection',
        'execute_action',
    },
)


def _row_has_sticky_cta(row: dict[str, Any] | None) -> bool:
    """True when a workflow/timeline row exposes a bottom sticky button contract."""
    if not row:
        return False
    action = str(row.get('action') or '').strip()
    if action == 'go_to_pod_capture':
        return bool(
            row.get('capture_ui')
            or row.get('show_pod_capture_button')
        )
    if action == 'go_to_evidence_capture':
        return bool(
            row.get('capture_ui')
            or row.get('requires_evidence_capture')
            or row.get('direct_execute')
        )
    if action in _TAPPABLE_CTA_ACTIONS:
        return True
    if row.get('direct_execute'):
        return True
    if row.get('show_pod_capture_button') or row.get('show_close_job_button'):
        return True
    return False


def _hint_has_sticky_cta(hint: dict[str, Any] | None) -> bool:
    return _row_has_sticky_cta(dict(hint or {}))


def _promote_first_pending_timeline_cta(
    workflow: dict[str, Any],
    hint: dict[str, Any],
    *,
    preview: list[Any] | None,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Promote the earliest pending non-POD timeline row to workflow + hint."""
    out_wf = dict(workflow or {})
    out_hint = dict(hint or {})
    first_pending = _first_pending_timeline_row(preview)
    if not first_pending or _row_is_pending_pod_capture(first_pending):
        return out_wf, out_hint
    first_pending = _enrich_pending_workflow_row(
        first_pending,
        shipment=shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
        timeline_preview=list(preview or []),
    )
    out_wf['primary_action'] = dict(first_pending)
    out_wf['next_action'] = dict(first_pending)
    out_hint = _hint_from_navigation_row(first_pending, pod_cod=None)
    return out_wf, out_hint


def _should_promote_first_pending_timeline_cta(
    workflow: dict[str, Any],
    hint: dict[str, Any],
    *,
    preview: list[Any] | None,
) -> bool:
    first_pending = _first_pending_timeline_row(preview)
    if not first_pending or _row_is_pending_pod_capture(first_pending):
        return False
    hint_action = str(hint.get('action') or '').strip()
    if hint_action in {'', 'refresh_job_detail'}:
        return True
    if hint_action == 'go_to_pod_capture':
        return True
    primary = dict((workflow or {}).get('primary_action') or {})
    pending_code = str(first_pending.get('action_code') or '').strip()
    hint_code = str(hint.get('action_code') or '').strip()
    if pending_code and hint_code and pending_code != hint_code:
        if hint_action in {'go_to_evidence_capture', 'execute_action', ''}:
            return True
    if not _row_has_sticky_cta(primary) and not _hint_has_sticky_cta(hint):
        return True
    if _row_has_sticky_cta(primary) and not _hint_has_sticky_cta(hint):
        return True
    return False


def _hint_from_navigation_row(
    row: dict[str, Any],
    *,
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hint: dict[str, Any] = {
        'action': str(row.get('action') or '').strip(),
        'screen': str(row.get('screen') or '').strip(),
        'action_code': str(row.get('action_code') or '').strip(),
        'job_closed': False,
        'show_completion_screen': False,
    }
    for key in (
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
        'reason',
        'execution_label',
        'action_name',
        'action_label',
        'english_label',
        'label',
        'requires_evidence_capture',
        'direct_execute',
        'show_close_job_button',
    ):
        if row.get(key) not in (None, '', []):
            hint[key] = row[key]
    if hint.get('action') == 'go_to_pod_capture':
        hint['show_pod_capture_button'] = True
        hint.setdefault(
            'reason',
            'Upload proof of delivery. Capture photos and video evidence, then tap Next.',
        )
    if hint.get('action') == 'go_to_evidence_capture' and str(
        row.get('ui_mode') or '',
    ) == 'job_close':
        hint['show_close_job_button'] = True
        hint.setdefault('reason', 'All steps complete. Tap Job Close to finish this leg.')
    if hint.get('action') == 'go_to_evidence_capture':
        label = _resolve_sticky_cta_button_label({**row, **hint})
        hint['button_label'] = label
        hint['execution_label'] = label
        hint['action_name'] = label
        hint.setdefault('reason', f'Tap {label} to continue.')
    hint = apply_pod_mobile_cta_contract(hint)
    if pod_cod is not None:
        from mobile_api.helpers.hard_copy_workflow_gate import coerce_digital_pod_capture_row

        hint = coerce_digital_pod_capture_row(hint, pod_cod=pod_cod)
    return hint


def reconcile_job_detail_cta(
    workflow: dict[str, Any] | None,
    next_hint: dict[str, Any] | None,
    *,
    timeline: dict[str, Any] | None = None,
    pod_cod: dict[str, Any] | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Promote the first pending workflow timeline row to workflow + hint.

    Uses workflow sequence order (Action Master map) so POD (seq 9) wins over
    End Job (seq 10) when both are still pending.
    """
    out_wf = dict(workflow or {})
    hint = dict(next_hint or {})
    pod = dict(pod_cod or {})
    preview = list((timeline or {}).get('timeline_preview') or [])
    log_evidence = dict(pod.get('log_evidence') or {})

    if _should_promote_first_pending_timeline_cta(
        out_wf,
        hint,
        preview=preview,
    ):
        out_wf, hint = _promote_first_pending_timeline_cta(
            out_wf,
            hint,
            preview=preview,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
        return out_wf, hint

    pod_row = _first_pending_timeline_row(
        preview,
        matcher=_row_is_pending_pod_capture,
    )
    pod_pending = bool(pod.get('pod_pending', False))

    pod_seq = int(pod_row.get('sequence_number') or 0) if pod_row else 0
    if (
        pod_pending
        and pod_row
        and _prior_timeline_steps_performed(preview, target_row=pod_row)
        and not _hint_covers_earlier_pending_step(
            hint,
            preview,
            before_sequence=pod_seq,
        )
        and _hint_needs_pod_cta(hint, pod_row=pod_row, workflow=out_wf)
    ):
        pod_row = _enrich_pending_workflow_row(
            pod_row,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
            timeline_preview=preview,
        )
        out_wf['primary_action'] = dict(pod_row)
        out_wf['next_action'] = dict(pod_row)
        hint = _hint_from_navigation_row(pod_row, pod_cod=pod)
        return out_wf, hint

    if pod.get('pod_compliant') and not pod.get('pod_pending'):
        from mobile_api.helpers.job_action_resolver import row_is_collect_payment_action

        cod_due = bool(
            pod.get('cod_pending')
            or (
                not pod.get('cod_collected')
                and str(getattr(shipment, 'order_type', None) or '').strip().upper()
                == 'COD'
            )
        )
        if cod_due and not pod.get('hard_pod_pending'):
            pay_row = _first_pending_timeline_row(
                preview,
                matcher=lambda row: row_is_collect_payment_action(row),
            )
            if pay_row and str(hint.get('action') or '').strip() in {
                '',
                'refresh_job_detail',
                'go_to_pod_capture',
            }:
                pay_row = _enrich_pending_workflow_row(
                    pay_row,
                    shipment=shipment,
                    tenant_schema=tenant_schema,
                    log_evidence=log_evidence,
                    timeline_preview=preview,
                )
                out_wf['primary_action'] = dict(pay_row)
                out_wf['next_action'] = dict(pay_row)
                hint = _hint_from_navigation_row(pay_row, pod_cod=pod)
                return out_wf, hint
        close_row = _first_pending_timeline_row(
            preview,
            matcher=lambda row: row_is_job_close_action(row),
        )
        if close_row and str(hint.get('action') or '').strip() in {'', 'refresh_job_detail'}:
            close_row = _enrich_pending_workflow_row(
                close_row,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=log_evidence,
                timeline_preview=preview,
            )
            out_wf['primary_action'] = dict(close_row)
            out_wf['next_action'] = dict(close_row)
            hint = _hint_from_navigation_row(close_row, pod_cod=pod)

    return out_wf, hint


def _timeline_unloading_completed_performed(preview: list[Any] | None) -> bool:
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        _timeline_unloading_completed_performed as _unloading_done,
    )

    return _unloading_done(preview)


def _pod_capture_phase_active(
    *,
    pod_cod: dict[str, Any] | None,
    timeline: dict[str, Any] | None,
    shipment: Any | None,
    hint: dict[str, Any],
    tenant_schema: str = '',
) -> bool:
    """True when the driver should see POD capture CTA + Delivered-stage badge."""
    from mobile_api.helpers.hard_copy_workflow_gate import derive_unloading_pending
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        find_pod_upload_row_in_timeline,
        timeline_pod_step_is_actionable,
    )
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        shipment_delivery_arrival_done,
        shipment_unloading_completed_done,
        shipment_unloading_done,
    )

    _ = tenant_schema
    if str(hint.get('action') or '').strip() == 'go_to_payment_collection':
        return False
    pod = dict(pod_cod or {})
    if (
        pod.get('pod_compliant')
        and not pod.get('pod_pending')
        and not pod.get('hard_pod_pending')
        and str(hint.get('action') or '').strip() != 'go_to_pod_capture'
    ):
        return False
    if str(hint.get('action') or '').strip() == 'go_to_evidence_capture':
        return False
    if derive_unloading_pending(shipment):
        return False
    if shipment is not None:
        if (
            shipment_unloading_done(shipment)
            and shipment_delivery_arrival_done(shipment)
            and not shipment_unloading_completed_done(shipment)
        ):
            return False

    preview = list((timeline or {}).get('timeline_preview') or [])
    pod_row = find_pod_upload_row_in_timeline(timeline)
    if pod_row and timeline_pod_step_is_actionable(
        pod_row,
        shipment=shipment,
        timeline_preview=preview,
    ):
        return True

    if str(hint.get('action') or '').strip() == 'go_to_pod_capture' or hint.get(
        'show_pod_capture_button',
    ):
        return bool(
            pod_row
            and timeline_pod_step_is_actionable(
                pod_row,
                shipment=shipment,
                timeline_preview=preview,
            )
        )

    pod = dict(pod_cod or {})
    if pod.get('pod_pending') and not pod.get('pod_compliant'):
        return bool(
            pod_row
            and timeline_pod_step_is_actionable(
                pod_row,
                shipment=shipment,
                timeline_preview=preview,
            )
        )

    return False


def _sync_workflow_pod_operational_stage(
    workflow: dict[str, Any],
    *,
    shipment: Any | None = None,
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Badge + metadata must read POD while digital upload is still pending."""
    pod = dict(pod_cod or {})
    if not pod.get('pod_pending', False):
        return dict(workflow or {})
    from iroad_tenants.operation_runtime.shipment_execution_stage import (
        STAGE_POD,
        derive_shipment_execution_stage,
        execution_stage_operational_label,
    )

    out = dict(workflow or {})
    stage = STAGE_POD
    if shipment is not None:
        derived = (derive_shipment_execution_stage(shipment) or '').strip()
        if derived:
            stage = derived
    if pod.get('pod_pending') and not pod.get('pod_compliant'):
        stage = STAGE_POD
    label = execution_stage_operational_label(stage) or 'Delivered'
    out['current_stage'] = label
    meta = dict(out.get('workflow_metadata') or {})
    meta['execution_sub_stage'] = stage
    meta['operational_stage'] = label
    out['workflow_metadata'] = meta
    return out


def _realign_workflow_operational_stage(
    workflow: dict[str, Any],
    *,
    primary: dict[str, Any] | None = None,
    shipment: Any | None = None,
) -> dict[str, Any]:
    """Keep badge/stage aligned with the sticky CTA — not premature COD/POD."""
    out = dict(workflow or {})
    row = dict(primary or out.get('primary_action') or {})
    recon = dict(out.get('reconciliation') or {})
    auth_status = (recon.get('authoritative_status') or '').strip()
    try:
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            derive_shipment_execution_stage,
            execution_stage_operational_label,
        )
        from mobile_api.helpers.job_action_resolver import (
            row_is_delivery_arrival_action,
            row_is_unloading_action,
            row_is_unloading_completed_action,
        )

        stage = ''
        if shipment is not None:
            stage = (derive_shipment_execution_stage(shipment) or '').strip()
        if not stage and auth_status:
            from tenant_workspace.models import TenantShipment

            mapped = {
                TenantShipment.ShipmentStatus.IN_TRANSIT: 'in_transit',
                TenantShipment.ShipmentStatus.AT_DELIVERY: 'delivery',
                TenantShipment.ShipmentStatus.LOADED: 'pre_transit',
                TenantShipment.ShipmentStatus.CREATED: 'pickup',
            }
            stage = mapped.get(auth_status, '')
        if row_is_delivery_arrival_action(row) or row_is_unloading_action(row):
            stage = 'in_transit' if auth_status == 'In Transit' else (stage or 'delivery')
        elif row_is_unloading_completed_action(row):
            stage = 'delivery'
        label = execution_stage_operational_label(stage) or out.get('current_stage') or ''
        if label:
            out['current_stage'] = label
            meta = dict(out.get('workflow_metadata') or {})
            meta['execution_sub_stage'] = stage or meta.get('execution_sub_stage') or ''
            meta['operational_stage'] = label
            out['workflow_metadata'] = meta
    except Exception:
        pass
    return out


def _align_workflow_driver_cta_contract(
    workflow: dict[str, Any],
    *,
    primary: dict[str, Any] | None = None,
    shipment: Any | None = None,
) -> dict[str, Any]:
    """
    Mobile sticky button reads ``workflow.next_action`` (Postman contract).

    When reconciliation sets ``primary_action`` only, mirror it to ``next_action``
    and seed ``allowed_actions`` so the driver app renders the CTA.
    """
    out = dict(workflow or {})
    row = dict(primary or out.get('primary_action') or {})
    if not _row_has_sticky_cta(row):
        return out
    row = _apply_pod_sticky_cta_labels(row)
    out['primary_action'] = dict(row)
    out['next_action'] = dict(row)
    allowed = [
        dict(item)
        for item in (out.get('allowed_actions') or [])
        if isinstance(item, dict)
    ]
    code = str(row.get('action_code') or '').strip().casefold()
    if code:
        without = [
            item
            for item in allowed
            if str(item.get('action_code') or '').strip().casefold() != code
        ]
        out['allowed_actions'] = [dict(row)] + without
    elif not allowed:
        out['allowed_actions'] = [dict(row)]
    meta = dict(out.get('workflow_metadata') or {})
    meta['allowed_action_count'] = len(out.get('allowed_actions') or [])
    out['workflow_metadata'] = meta
    return _realign_workflow_operational_stage(
        out,
        primary=row,
        shipment=shipment,
    )


_GENERIC_STICKY_LABELS = frozenset(
    {
        '',
        'next',
        'submit',
        'capturing action evidences',
    },
)


def _resolve_action_display_label(row: dict[str, Any]) -> str:
    """Human Operation Action label for the job-detail sticky button."""
    for key in (
        'action_label',
        'english_label',
        'label',
        'execution_label',
        'action_name',
    ):
        text = str(row.get(key) or '').strip()
        if text.casefold() not in _GENERIC_STICKY_LABELS:
            return text
    if str(row.get('ui_mode') or '').strip() == 'job_close':
        return 'Job Close'
    if str(row.get('action') or '').strip() == 'go_to_pod_capture':
        return 'POD'
    return ''


def _resolve_sticky_cta_button_label(row: dict[str, Any]) -> str:
    """
    Sticky footer on Job Detail — show the workflow step name (e.g. Start Unloading).

    ``capture_ui.primary_button.label`` stays ``Next`` for the evidence screen itself.
    """
    action_label = _resolve_action_display_label(row)
    if action_label:
        return action_label
    button = dict((row.get('capture_ui') or {}).get('primary_button') or {})
    return str(button.get('label') or 'Next').strip() or 'Next'


def _apply_pod_sticky_cta_labels(row: dict[str, Any]) -> dict[str, Any]:
    """Mobile sticky button — Operation Action name, not evidence-screen Next."""
    out = dict(row or {})
    label = _resolve_sticky_cta_button_label(out)
    out['button_label'] = label
    out['execution_label'] = label
    out['action_name'] = label
    out.pop('movement_status_impact', None)
    requirements = dict(out.get('execution_requirements') or {})
    if requirements.get('movement_status_impact'):
        requirements['movement_status_impact'] = ''
        out['execution_requirements'] = requirements
    return out


def finalize_job_detail_workflow_cta(
    workflow: dict[str, Any] | None,
    next_hint: dict[str, Any] | None,
    *,
    timeline: dict[str, Any] | None = None,
    pod_cod: dict[str, Any] | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Last-mile alignment for the sticky POD button.

    Mobile reads ``workflow.primary_action`` (and often ``allowed_actions``) while
    helper text may come from ``next_action_hint``. When those diverge, drivers see
    POD copy without a tappable CTA.
    """
    from mobile_api.helpers.action_navigation_metadata import (
        sync_workflow_primary_from_next_hint,
    )
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        find_pod_upload_row_in_timeline,
    )

    out_wf = dict(workflow or {})
    hint = apply_pod_mobile_cta_contract(dict(next_hint or {}))
    pod = dict(pod_cod or {})
    log_evidence = dict(
        (pod.get('compliance_integrity') or {}).get('log_evidence')
        or pod.get('log_evidence')
        or {},
    )

    is_pod = _pod_capture_phase_active(
        pod_cod=pod,
        timeline=timeline,
        shipment=shipment,
        hint=hint,
        tenant_schema=tenant_schema,
    )
    if not is_pod:
        out_wf = sync_workflow_primary_from_next_hint(
            out_wf,
            hint,
            shipment=shipment,
            tenant_schema=tenant_schema,
        )
        preview = list((timeline or {}).get('timeline_preview') or [])
        if _should_promote_first_pending_timeline_cta(
            out_wf,
            hint,
            preview=preview,
        ):
            out_wf, hint = _promote_first_pending_timeline_cta(
                out_wf,
                hint,
                preview=preview,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=log_evidence,
            )
            out_wf = sync_workflow_primary_from_next_hint(
                out_wf,
                hint,
                shipment=shipment,
                tenant_schema=tenant_schema,
            )
        primary = dict(out_wf.get('primary_action') or {})
        if _row_has_sticky_cta(primary):
            out_wf['primary_action'] = _apply_pod_sticky_cta_labels(primary)
            hint = _apply_pod_sticky_cta_labels(hint)
        out_wf = _align_workflow_driver_cta_contract(
            out_wf,
            primary=dict(out_wf.get('primary_action') or {}),
            shipment=shipment,
        )
        return out_wf, hint

    preview = list((timeline or {}).get('timeline_preview') or [])

    if str(hint.get('action') or '').strip() != 'go_to_pod_capture' and not hint.get(
        'show_pod_capture_button',
    ):
        pod_row = find_pod_upload_row_in_timeline(timeline)
        if pod_row:
            pod_row = _enrich_pending_workflow_row(
                pod_row,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=log_evidence,
                timeline_preview=preview,
            )
            hint = _hint_from_navigation_row(pod_row, pod_cod=pod)
        else:
            hint = apply_pod_mobile_cta_contract(
                _hint_from_navigation_row(
                    _workflow_row_from_pod_hint(hint),
                    pod_cod=pod,
                ),
            )

    out_wf = sync_workflow_primary_from_next_hint(
        out_wf,
        hint,
        shipment=shipment,
        tenant_schema=tenant_schema,
    )

    if _workflow_primary_lags_pod_hint(out_wf, hint):
        pod_row = find_pod_upload_row_in_timeline(timeline)
        if pod_row:
            pod_row = _enrich_pending_workflow_row(
                pod_row,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=log_evidence,
                timeline_preview=preview,
            )
        else:
            pod_row = _workflow_row_from_pod_hint(hint)
        pod_row['show_pod_capture_button'] = True
        pod_row.pop('requires_evidence_capture', None)
        out_wf['primary_action'] = dict(pod_row)
        out_wf['next_action'] = dict(pod_row)

    allowed = list(out_wf.get('allowed_actions') or [])
    has_pod_allowed = any(
        isinstance(row, dict) and row_has_digital_pod_upload(row) for row in allowed
    )
    primary = dict(out_wf.get('primary_action') or {})
    if not has_pod_allowed and row_has_digital_pod_upload(primary):
        out_wf['allowed_actions'] = [primary] + allowed
        meta = dict(out_wf.get('workflow_metadata') or {})
        meta['allowed_action_count'] = len(out_wf['allowed_actions'])
        out_wf['workflow_metadata'] = meta

    primary = dict(out_wf.get('primary_action') or {})
    if primary:
        primary['action'] = 'go_to_pod_capture'
        primary['screen'] = primary.get('screen') or 'pod_capture'
        primary['show_pod_capture_button'] = True
        primary.pop('requires_evidence_capture', None)
        button = dict((primary.get('capture_ui') or {}).get('primary_button') or {})
        if button.get('label'):
            primary['button_label'] = button['label']
            primary.setdefault('execution_label', button['label'])
            primary.setdefault('action_name', button['label'])
        out_wf['primary_action'] = primary
        next_row = dict(out_wf.get('next_action') or {})
        if not next_row:
            out_wf['next_action'] = dict(primary)
        elif str(next_row.get('action') or '').strip() != 'go_to_pod_capture':
            out_wf['next_action'] = dict(primary)

    from mobile_api.helpers.hard_copy_workflow_gate import (
        coerce_digital_pod_capture_row,
        enforce_job_detail_pod_digital_first,
        hard_copy_step_due,
    )

    out_wf, hint = enforce_job_detail_pod_digital_first(out_wf, hint, pod_cod=pod)
    if hard_copy_step_due(pod):
        primary = dict(out_wf.get('primary_action') or {})
    else:
        primary = coerce_digital_pod_capture_row(
            dict(out_wf.get('primary_action') or {}),
            pod_cod=pod,
        )
        out_wf['primary_action'] = primary
        if str(dict(out_wf.get('next_action') or {}).get('action') or '') == 'go_to_pod_capture':
            out_wf['next_action'] = dict(primary)

    out_wf = _sync_workflow_pod_operational_stage(
        out_wf,
        shipment=shipment,
        pod_cod=pod,
    )
    primary = dict(out_wf.get('primary_action') or {})
    if primary:
        out_wf['primary_action'] = _apply_pod_sticky_cta_labels(primary)
        next_row = dict(out_wf.get('next_action') or {})
        if next_row:
            out_wf['next_action'] = _apply_pod_sticky_cta_labels(next_row)
    hint = _apply_pod_sticky_cta_labels(hint)
    hint['show_pod_capture_button'] = True

    out_wf = _align_workflow_driver_cta_contract(
        out_wf,
        primary=dict(out_wf.get('primary_action') or {}),
        shipment=shipment,
    )
    return out_wf, hint
