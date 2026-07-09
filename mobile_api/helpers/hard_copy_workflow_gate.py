"""Shared hard-copy POD workflow gate helpers (Job Detail + hints)."""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantShipment

HARD_COPY_CAPTURE_MODE = 'hard_copy_confirmation'
DIGITAL_CAPTURE_MODE = 'digital_evidence'


def derive_unloading_pending(shipment: Any | None) -> bool:
    """
    Delivery-phase prerequisites (arrival + unloading) must complete before POD.

    Scoped to post-loading shipment statuses so pickup/loading are unaffected.
    """
    if shipment is None:
        return False
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    if status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.LOADED,
    }:
        return False
    if status not in {
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }:
        return False
    try:
        from iroad_tenants.operation_runtime.shipment_execution_stage import (
            shipment_delivery_arrival_done,
            shipment_unloading_completed_done,
            shipment_unloading_done,
        )

        if not shipment_delivery_arrival_done(shipment):
            return True
        if not shipment_unloading_done(shipment):
            return True
        return not shipment_unloading_completed_done(shipment)
    except Exception:
        return False


def digital_evidence_complete_for_pod_cod(pod_cod: dict[str, Any] | None) -> bool:
    """True only when Action Log marks digital POD uploaded — never column flags alone."""
    pod = dict(pod_cod or {})
    integrity = dict(pod.get('compliance_integrity') or {})
    evidence = dict(integrity.get('log_evidence') or pod.get('log_evidence') or {})
    return bool(evidence.get('pod_uploaded'))


def hard_copy_workflow_gate_open(pod_cod: dict[str, Any] | None) -> bool:
    """
    Hard-copy step may drive CTA/hints.

    Digital-first HARD jobs require digital evidence before hard copy.
    Hard-only jobs omit ``digital_evidence`` from ``capture_steps`` explicitly.
    """
    pod = dict(pod_cod or {})
    block = dict(pod.get('hard_copy_confirmation') or {})
    if not (block.get('applicable') or block.get('required')):
        return False
    capture_steps = list(
        pod.get('capture_steps') or ['digital_evidence', 'hard_copy_confirmation'],
    )
    if 'digital_evidence' in capture_steps:
        return digital_evidence_complete_for_pod_cod(pod)
    return True


def unloading_pending_for_pod_workflow(pod_cod: dict[str, Any] | None) -> bool:
    """Start Unloading must complete before POD / hard-copy steps."""
    return bool(dict(pod_cod or {}).get('unloading_pending'))


def hard_copy_wizard_next_allowed(pod_cod: dict[str, Any] | None) -> bool:
    """True when mobile may route digital Next → hard-copy confirmation."""
    pod = dict(pod_cod or {})
    block = dict(pod.get('hard_copy_confirmation') or {})
    return bool(block.get('applicable'))


def hard_copy_step_due(pod_cod: dict[str, Any] | None) -> bool:
    """Hard-copy custody is outstanding and prerequisite steps are complete."""
    pod = dict(pod_cod or {})
    if not pod.get('hard_pod_pending'):
        return False
    block = dict(pod.get('hard_copy_confirmation') or {})
    if not (block.get('applicable') or block.get('required')):
        return False
    if not block.get('actionable'):
        return False
    if unloading_pending_for_pod_workflow(pod):
        return False
    capture_steps = list(
        pod.get('capture_steps') or ['digital_evidence', 'hard_copy_confirmation'],
    )
    if 'digital_evidence' in capture_steps and not digital_evidence_complete_for_pod_cod(pod):
        return False
    return hard_copy_workflow_gate_open(pod)


def _row_targets_hard_copy_screen(row: dict[str, Any]) -> bool:
    mode = str(
        row.get('capture_mode') or row.get('active_step') or row.get('ui_mode') or '',
    ).strip().casefold()
    if mode in {HARD_COPY_CAPTURE_MODE, 'hard_pod_collection_confirmation'}:
        return True
    if row.get('confirmation_ui'):
        return True
    if str(row.get('screen_title') or '').strip().casefold().startswith('hard pod'):
        return True
    return False


def coerce_digital_pod_capture_row(
    row: dict[str, Any] | None,
    *,
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Force Upload POD step 1 (digital evidence) on navigation rows.

    Mobile opens ``capture_mode`` / ``confirmation_ui`` directly — hard copy must
    not leak before digital POD is logged.
    """
    out = dict(row or {})
    if str(out.get('action') or '').strip() != 'go_to_pod_capture':
        return out
    if hard_copy_step_due(pod_cod):
        return out
    if not _row_targets_hard_copy_screen(out) and not out.get('hard_copy_confirmation'):
        out.pop('confirmation_ui', None)
        return out

    from mobile_api.pod_capture.services.pod_section_metadata import (
        DIGITAL_EVIDENCE_SCREEN_TITLE,
        UI_MODE_DIGITAL_EVIDENCE,
        build_pod_capture_steps,
    )

    pod = dict(pod_cod or {})
    hard_wizard = hard_copy_step_due(pod)
    out['capture_mode'] = DIGITAL_CAPTURE_MODE
    out['active_step'] = DIGITAL_CAPTURE_MODE
    out['ui_mode'] = UI_MODE_DIGITAL_EVIDENCE
    out['screen_title'] = DIGITAL_EVIDENCE_SCREEN_TITLE
    out.pop('confirmation_ui', None)
    out.pop('capture_step_query', None)
    block = dict(out.get('hard_copy_confirmation') or {})
    if block:
        block = dict(block)
        block.pop('confirmation_ui', None)
        out['hard_copy_confirmation'] = block
    out['pod_capture_steps'] = list(
        pod.get('capture_steps') or build_pod_capture_steps(hard_pod=hard_wizard),
    )
    out['hard_pod'] = hard_wizard
    out['includes_hard_copy'] = hard_wizard
    return out


def enforce_job_detail_pod_digital_first(
    workflow: dict[str, Any] | None,
    next_hint: dict[str, Any] | None,
    *,
    pod_cod: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scrub premature hard-copy navigation from workflow + hint."""
    wf = dict(workflow or {})
    hint = coerce_digital_pod_capture_row(dict(next_hint or {}), pod_cod=pod_cod)
    for key in ('primary_action', 'next_action'):
        row = wf.get(key)
        if isinstance(row, dict):
            wf[key] = coerce_digital_pod_capture_row(row, pod_cod=pod_cod)
    wf['allowed_actions'] = [
        coerce_digital_pod_capture_row(dict(item), pod_cod=pod_cod)
        if isinstance(item, dict)
        else item
        for item in (wf.get('allowed_actions') or [])
    ]
    return wf, hint


def _empty_hard_copy_checklist_block(block: dict[str, Any] | None) -> dict[str, Any]:
    """Remove checklist payloads mobile may open before hard-copy step is due."""
    out = dict(block or {})
    out['documents'] = []
    out['pages'] = []
    out.pop('confirmation_ui', None)
    out['ui_mode'] = ''
    out['screen_title'] = ''
    out['actionable'] = False
    out['submit_allowed'] = False
    return out


def _scrub_capture_ui_hard_copy_wizard(capture_ui: dict[str, Any] | None) -> dict[str, Any]:
    ui = dict(capture_ui or {})
    primary = dict(ui.get('primary_button') or {})
    primary.pop('wizard_next_step', None)
    ui['primary_button'] = primary
    return ui


def scrub_pod_capture_row_before_hard_copy_due(
    row: dict[str, Any] | None,
    *,
    pod_cod: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Strip hard-copy wizard contracts from workflow/timeline rows until step 2 is due."""
    if hard_copy_step_due(pod_cod):
        return dict(row or {})
    out = coerce_digital_pod_capture_row(dict(row or {}), pod_cod=pod_cod)
    out.pop('confirmation_ui', None)
    out['hard_pod'] = False
    out['includes_hard_copy'] = False
    if str(out.get('action') or '').strip() == 'go_to_pod_capture':
        out['pod_capture_steps'] = [DIGITAL_CAPTURE_MODE]
    block = dict(out.get('hard_copy_confirmation') or {})
    if block:
        out['hard_copy_confirmation'] = _empty_hard_copy_checklist_block(block)
    if out.get('capture_ui'):
        out['capture_ui'] = _scrub_capture_ui_hard_copy_wizard(out['capture_ui'])
    requirements = dict(out.get('execution_requirements') or {})
    if requirements.get('capture_ui'):
        requirements['capture_ui'] = _scrub_capture_ui_hard_copy_wizard(
            requirements.get('capture_ui'),
        )
        out['execution_requirements'] = requirements
    return out


def scrub_premature_hard_pod_job_detail_payload(
    *,
    workflow: dict[str, Any] | None,
    pod_cod: dict[str, Any] | None,
    next_hint: dict[str, Any] | None = None,
    timeline: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Mobile treats ``pod_cod.hard_pod_pending`` and checklist ``pages`` as open Hard POD.

    Keep milestone CTAs on evidence capture until digital POD is logged.
    """
    from mobile_api.pod_capture.services.pod_section_metadata import build_pod_capture_steps

    wf = dict(workflow or {})
    pod = dict(pod_cod or {})
    hint = dict(next_hint or {})
    unloading_pending = unloading_pending_for_pod_workflow(pod)
    digital_complete = digital_evidence_complete_for_pod_cod(pod)
    hard_copy_due = hard_copy_step_due(pod)

    if unloading_pending or not digital_complete:
        if unloading_pending:
            pod['hard_pod_pending'] = False
            pod['pod_capture_due'] = False
            pod['hard_pod_capture_due'] = False
        pod['capture_steps'] = build_pod_capture_steps(hard_pod=False)
        block = _empty_hard_copy_checklist_block(dict(pod.get('hard_copy_confirmation') or {}))
        pod['hard_copy_confirmation'] = block
    elif digital_complete and not hard_copy_due:
        pod['hard_pod_pending'] = False
        pod['hard_pod_capture_due'] = False
        block = _empty_hard_copy_checklist_block(dict(pod.get('hard_copy_confirmation') or {}))
        pod['hard_copy_confirmation'] = block

    wf['allowed_actions'] = [
        scrub_pod_capture_row_before_hard_copy_due(dict(item), pod_cod=pod)
        if isinstance(item, dict)
        else item
        for item in (wf.get('allowed_actions') or [])
    ]
    for key in ('primary_action', 'next_action'):
        row = wf.get(key)
        if isinstance(row, dict):
            wf[key] = scrub_pod_capture_row_before_hard_copy_due(dict(row), pod_cod=pod)

    if unloading_pending or str(hint.get('action') or '') == 'go_to_evidence_capture':
        hint['hard_pod_capture_due'] = False
        hint['pod_capture_due'] = False
        hint.pop('confirmation_ui', None)
        hint.pop('hard_copy_confirmation', None)
    elif hard_copy_due:
        hint['hard_pod_capture_due'] = True
    else:
        hint['hard_pod_capture_due'] = False
        hint['pod_capture_due'] = bool(
            str(hint.get('action') or '') == 'go_to_pod_capture'
            or hint.get('show_pod_capture_button'),
        )

    preview = list((timeline or {}).get('timeline_preview') or wf.get('timeline_preview') or [])
    if preview:
        scrubbed = coerce_timeline_pod_navigation_rows(preview, pod_cod=pod)
        wf['timeline_preview'] = scrubbed
        if timeline is not None:
            timeline = dict(timeline)
            timeline['timeline_preview'] = scrubbed

    return wf, pod, hint


def coerce_timeline_pod_navigation_rows(
    events: list[dict[str, Any]] | None,
    *,
    pod_cod: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Timeline preview rows must not advertise hard copy before digital POD."""
    out: list[dict[str, Any]] = []
    for event in list(events or []):
        if not isinstance(event, dict):
            continue
        row = scrub_pod_capture_row_before_hard_copy_due(dict(event), pod_cod=pod_cod)
        out.append(row)
    return out
