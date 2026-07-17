"""
Mobile navigation metadata for Action Master rows (timeline taps, allowed actions).

Upload POD (A7 / OA-0008): digital evidence first; hard-copy checklist second when
``pod_type`` is Hard and delivery-note custody applies.

Hard-copy-only rows (A7H): custody checklist only — no digital wizard.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.evidence_requirement_flags import sync_row_evidence_flags
from mobile_api.helpers.cod_amount import build_cod_payment_display
from iroad_tenants.operation_runtime.movement_action_validator import (
    is_empty_move_catalog_action,
)
from mobile_api.helpers.empty_move_action_resolver import (
    action_is_empty_move_lifecycle,
    row_is_empty_move_action,
)
from mobile_api.helpers.job_action_resolver import (
    action_code_is_collect_payment,
    action_code_is_job_close,
    action_is_collect_payment,
    action_is_job_close,
    row_is_collect_payment_action,
    row_is_job_close_action,
)

PAYMENT_COLLECT_API_PATH = '/api/v1/mobile/driver/payments/collect/'
from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.execution.evidence.constants import POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
    is_pod_upload_action,
)
from mobile_api.pod_capture.services.pod_section_metadata import (
    DIGITAL_EVIDENCE_SCREEN_TITLE,
    HARD_COPY_SCREEN_TITLE,
    UI_MODE_DIGITAL_EVIDENCE,
    UI_MODE_HARD_POD_CONFIRMATION,
    build_hard_copy_confirmation_block,
    build_pod_capture_steps,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
    find_pod_upload_row_in_allowed,
    row_has_digital_pod_upload,
)

HARD_COPY_CONFIRMATION_SCREEN = 'hard_copy_confirmation'
POD_CAPTURE_SCREEN = 'pod_capture'
DIGITAL_EVIDENCE_SCREEN = 'digital_evidence'
EVIDENCE_CAPTURE_SCREEN = 'evidence_capture'
GO_TO_EVIDENCE_CAPTURE_ACTION = 'go_to_evidence_capture'


def is_without_scope_action(action: Any | None) -> bool:
    from iroad_tenants.operation_runtime.movement_action_validator import (
        is_without_scope_catalog_action,
    )

    return is_without_scope_catalog_action(action)


def row_is_without_scope_action(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    req = dict(row.get('execution_requirements') or {})
    cat = str(
        req.get('sequence_category')
        or row.get('sequence_category')
        or row.get('action_category')
        or '',
    ).strip().casefold()
    if cat == 'without':
        return True
    scope = str(row.get('action_scope') or req.get('action_scope') or '').strip().casefold()
    if scope == 'without':
        return True
    return is_without_scope_action(_action_like_from_row(row))


def apply_standalone_evidence_capture_navigation_to_action_row(
    row: dict[str, Any],
    *,
    action: Any | None = None,
    submit_contract: dict[str, Any] | None = None,
    submit_button_label: str = 'Submit',
) -> dict[str, Any]:
    """
    Evidence capture screen decoupled from job sequence and empty-move workflow.

    Used for support reporting and ``without``-scope Operation Actions.
    """
    from mobile_api.execution.evidence.evidence_capture_ui import (
        UI_MODE_STANDALONE_EVIDENCE,
        build_standalone_evidence_capture_ui,
    )
    from mobile_api.helpers.evidence_requirement_flags import (
        normalize_evidence_requirements,
    )

    out = dict(row)
    out['screen'] = EVIDENCE_CAPTURE_SCREEN
    out['action'] = GO_TO_EVIDENCE_CAPTURE_ACTION
    out['ui_mode'] = UI_MODE_STANDALONE_EVIDENCE
    out['linked_job_flow'] = False
    out['flow_context'] = 'standalone'
    out['requires_evidence_capture'] = True
    out['direct_execute'] = False

    requirements = dict(out.get('execution_requirements') or {})
    requirements['gps'] = True
    requirements.setdefault('photo_enabled', True)
    requirements.setdefault('video_enabled', True)
    requirements.setdefault('photo_min_count', 0)
    requirements.setdefault('video_min_count', 0)
    requirements.setdefault('video_max_duration_seconds', POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS)
    requirements.setdefault('note', True)
    requirements.setdefault('note_required', False)
    requirements.update(
        {
            'direct_execute': False,
            'requires_evidence_capture': True,
            'capture_mode': UI_MODE_STANDALONE_EVIDENCE,
            'allow_submit_without_media': True,
        },
    )
    requirements = normalize_evidence_requirements(requirements)
    out['execution_requirements'] = requirements

    act = action or _action_like_from_row(out)
    action_code = str(out.get('action_code') or getattr(act, 'action_code', '') or '').strip()
    screen_title = str(
        out.get('screen_title')
        or out.get('execution_label')
        or out.get('action_name')
        or out.get('label')
        or getattr(act, 'english_label', '')
        or DIGITAL_EVIDENCE_SCREEN_TITLE,
    ).strip()
    out['screen_title'] = screen_title
    out['capture_ui'] = build_standalone_evidence_capture_ui(
        requirements,
        action_code=action_code,
        screen_title=screen_title,
        submit_button_label=submit_button_label,
    )
    out['allow_submit_without_media'] = bool(requirements.get('allow_submit_without_media'))
    out['requires_gps'] = True
    if submit_contract:
        out['submit_contract'] = dict(submit_contract)
    elif action_code:
        from mobile_api.execution.evidence.evidence_capture_ui import (
            EXECUTE_ACTION_SUBMIT_ENDPOINT,
        )

        out['submit_contract'] = {
            'type': 'execute_action',
            'endpoint': EXECUTE_ACTION_SUBMIT_ENDPOINT,
            'method': 'POST',
            'payload': {
                'action_code': action_code,
                'job_type': '{job_type}',
                'job_id': '{job_id}',
                'note': '{note}',
                'media': '{evidence_media}',
                'latitude': '{latitude}',
                'longitude': '{longitude}',
            },
        }
    return sync_row_evidence_flags(out)


def apply_evidence_capture_navigation_to_action_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    """Generic driver action — optional photo/video evidence screen before execute."""
    from mobile_api.execution.evidence.evidence_capture_ui import (
        build_generic_evidence_capture_ui,
    )
    from mobile_api.helpers.evidence_requirement_flags import (
        normalize_evidence_requirements,
    )

    out = dict(row)
    out['screen'] = EVIDENCE_CAPTURE_SCREEN
    out['action'] = GO_TO_EVIDENCE_CAPTURE_ACTION
    out['requires_evidence_capture'] = True
    out['direct_execute'] = False
    requirements = dict(out.get('execution_requirements') or {})
    if not requirements.get('photo_enabled') and not requirements.get('video_enabled'):
        requirements.setdefault('photo_enabled', True)
        requirements.setdefault('video_enabled', True)
        requirements.setdefault('photo_min_count', 0)
        requirements.setdefault('video_min_count', 0)
        requirements.setdefault('video_max_duration_seconds', POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS)
    requirements.update(
        {
            'direct_execute': False,
            'requires_evidence_capture': True,
            'capture_mode': requirements.get('capture_mode') or 'optional_evidence',
        },
    )
    requirements = normalize_evidence_requirements(requirements)
    out['execution_requirements'] = requirements
    action_code = str(out.get('action_code') or '').strip()
    screen_title = str(
        out.get('screen_title')
        or out.get('execution_label')
        or out.get('action_name')
        or DIGITAL_EVIDENCE_SCREEN_TITLE,
    ).strip()
    if not out.get('screen_title'):
        screen_title = DIGITAL_EVIDENCE_SCREEN_TITLE
    out['screen_title'] = screen_title
    out['capture_ui'] = build_generic_evidence_capture_ui(
        requirements,
        action_code=action_code,
        screen_title=screen_title,
    )
    out['allow_submit_without_media'] = bool(requirements.get('allow_submit_without_media'))
    return sync_row_evidence_flags(out)


def is_hard_copy_navigation_action(action: Any | None) -> bool:
    if action is None:
        return False
    if getattr(action, 'hard_copy_collection', False):
        return True
    return (getattr(action, 'action_code', '') or '').strip().upper() == (
        CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE
    )


def is_hard_copy_only_navigation_action(action: Any | None) -> bool:
    """Hard custody checklist only — not combined Upload POD (digital + hard)."""
    if not is_hard_copy_navigation_action(action):
        return False
    return not is_pod_upload_action(action)


def _shipment_hard_pod_type(shipment: Any | None) -> bool:
    return pod_cod_policy.shipment_requires_hard_copy(shipment)


def _hard_pod_includes_wizard_hard_copy_step(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> bool:
    """Hard POD jobs include a wizard step 2 after digital — metadata only, not active CTA."""
    if not _shipment_hard_pod_type(shipment):
        return False
    return pod_cod_policy.hard_pod_stage_reached(
        shipment,
        log_evidence=log_evidence,
    )


def _digital_pod_complete(
    shipment: Any | None,
    *,
    log_evidence: dict[str, bool] | None = None,
    tenant_schema: str = '',
) -> bool:
    """Digital POD is complete only when Action Log evidence exists — not column flags."""
    _ = shipment, tenant_schema
    evidence = log_evidence or {}
    return bool(evidence.get('pod_uploaded'))


def _hard_copy_applicable(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> tuple[bool, dict[str, Any]]:
    if not _shipment_hard_pod_type(shipment):
        return False, {}
    block = build_hard_copy_confirmation_block(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
    applicable = bool(block.get('required') or block.get('applicable'))
    return applicable, block


def build_hard_copy_navigation_payload(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Checklist contract for Hard POD Collection Confirmation UI."""
    if not _digital_pod_complete(
        shipment,
        log_evidence=log_evidence,
        tenant_schema=tenant_schema,
    ):
        return {}
    try:
        from mobile_api.helpers.hard_copy_workflow_gate import derive_unloading_pending

        if derive_unloading_pending(shipment):
            return {}
    except Exception:
        pass
    applicable, block = _hard_copy_applicable(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
    if not applicable or not block.get('pending') or not block.get('actionable'):
        return {}
    return {
        'screen': POD_CAPTURE_SCREEN,
        'action': 'go_to_pod_capture',
        'capture_mode': HARD_COPY_CONFIRMATION_SCREEN,
        'active_step': 'hard_copy_confirmation',
        'ui_mode': UI_MODE_HARD_POD_CONFIRMATION,
        'screen_title': HARD_COPY_SCREEN_TITLE,
        'pod_capture_steps': build_pod_capture_steps(hard_pod=True),
        'hard_pod': True,
        'includes_hard_copy': True,
        'hard_copy_confirmation': block,
        'confirmation_ui': dict(block.get('confirmation_ui') or {}),
    }


def _ensure_pod_row_capture_ui(
    row: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    has_hard_copy_step: bool = False,
    allow_hard_copy_wizard_next: bool = False,
) -> dict[str, Any]:
    """Attach digital POD ``capture_ui`` when Action Master row omitted it (label-only POD)."""
    out = dict(row)
    if out.get('capture_ui'):
        return out
    from mobile_api.execution.evidence.constants import (
        POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
    )
    from mobile_api.pod_capture.policy.pod_capture_policy import (
        build_pod_capture_requirements,
    )
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        digital_action_code_from_action,
    )
    from mobile_api.pod_capture.services.pod_section_metadata import (
        build_digital_capture_ui,
    )

    requirements = build_pod_capture_requirements(
        action,
        pod_capture_type='digital',
        shipment=shipment,
    )
    requirements['capture_mode'] = 'digital_evidence'
    requirements['video_max_duration_seconds'] = int(
        requirements.get('video_max_duration_seconds')
        or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    )
    digital_code = (
        digital_action_code_from_action(action, tenant_schema=tenant_schema)
        or (out.get('action_code') or '').strip()
    )
    out['capture_ui'] = build_digital_capture_ui(
        requirements,
        has_hard_copy_step=has_hard_copy_step,
        allow_hard_copy_wizard_next=allow_hard_copy_wizard_next,
        digital_action_code=digital_code,
    )
    if digital_code and not out.get('action_code'):
        out['action_code'] = digital_code
    return out


def apply_pod_upload_navigation(
    row: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Digital POD first; hard-copy step second when ``hard_pod`` applies.

    Mobile reads ``hard_pod`` / ``includes_hard_copy`` to decide whether step 2
  exists after digital capture completes.
    """
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        row_has_digital_pod_upload,
    )

    if not is_pod_upload_action(action):
        if row_has_digital_pod_upload(row):
            action = _action_like_from_row(row)
        else:
            return row

    hard_applicable, hard_block = _hard_copy_applicable(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
    try:
        from mobile_api.helpers.hard_copy_workflow_gate import derive_unloading_pending

        if derive_unloading_pending(shipment):
            hard_wizard_step = False
            hard_block = {}
            hard_applicable = False
    except Exception:
        pass
    digital_complete = _digital_pod_complete(
        shipment,
        log_evidence=log_evidence,
        tenant_schema=tenant_schema,
    )
    hard_wizard_step = _hard_pod_includes_wizard_hard_copy_step(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )

    if digital_complete and hard_applicable and bool(hard_block.get('pending')):
        navigation = build_hard_copy_navigation_payload(
            shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
        if navigation:
            out = dict(row)
            out.update(navigation)
            out['pod_capture_steps'] = build_pod_capture_steps(hard_pod=True)
            return out

    capture_steps = build_pod_capture_steps(
        hard_pod=hard_wizard_step and bool(hard_block.get('pending') or not digital_complete),
    )

    out = dict(row)
    capture_ui = row.get('capture_ui')
    if digital_complete and hard_applicable and not hard_block.get('pending'):
        out.update(
            {
                'hard_pod': True,
                'includes_hard_copy': True,
                'pod_capture_steps': capture_steps,
            },
        )
        return out

    out.update(
        {
            'screen': POD_CAPTURE_SCREEN,
            'action': 'go_to_pod_capture',
            'capture_mode': DIGITAL_EVIDENCE_SCREEN,
            'active_step': DIGITAL_EVIDENCE_SCREEN,
            'ui_mode': UI_MODE_DIGITAL_EVIDENCE,
            'screen_title': DIGITAL_EVIDENCE_SCREEN_TITLE,
            'pod_capture_steps': capture_steps,
            'hard_pod': hard_wizard_step,
            'includes_hard_copy': hard_wizard_step,
        },
    )
    if hard_wizard_step:
        out['hard_copy_confirmation'] = hard_block
    if capture_ui:
        out['capture_ui'] = capture_ui
    out = _ensure_pod_row_capture_ui(
        out,
        action,
        shipment=shipment,
        tenant_schema=tenant_schema,
        has_hard_copy_step=hard_wizard_step and bool(hard_block.get('pending') or not digital_complete),
        allow_hard_copy_wizard_next=bool(hard_applicable),
    )
    out.pop('confirmation_ui', None)
    if shipment is not None:
        try:
            from iroad_tenants.operation_runtime.pod_action import build_shipment_document_gate

            document_gate = build_shipment_document_gate(
                shipment,
                action=action,
                tenant_schema=tenant_schema,
            )
            if document_gate.get('message'):
                capture_ui = dict(out.get('capture_ui') or {})
                capture_ui['submit_blocked'] = True
                capture_ui['submit_blocked_reason'] = document_gate['message']
                primary = dict(capture_ui.get('primary_button') or {})
                primary['disabled'] = True
                primary.pop('wizard_next_step', None)
                primary['complete_upload_after_execute'] = True
                capture_ui['primary_button'] = primary
                out['capture_ui'] = capture_ui
                out['shipment_document_required'] = True
                out['shipment_document_ready'] = False
                out['shipment_document_message'] = document_gate['message']
            elif not hard_applicable:
                capture_ui = dict(out.get('capture_ui') or {})
                primary = dict(capture_ui.get('primary_button') or {})
                primary.pop('wizard_next_step', None)
                primary['complete_upload_after_execute'] = True
                capture_ui['primary_button'] = primary
                out['capture_ui'] = capture_ui
        except Exception:
            pass
    return sync_row_evidence_flags(out)


def apply_hard_copy_navigation_to_action_row(
    row: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Enrich an allowed-action row for hard-copy-only or combined POD upload.
    """
    if is_pod_upload_action(action):
        return apply_pod_upload_navigation(
            row,
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    if not is_hard_copy_only_navigation_action(action):
        return row

    navigation = build_hard_copy_navigation_payload(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
    if not navigation:
        return row

    row = dict(row)
    row.update(navigation)
    row['requires_gps'] = False
    row['requires_photo'] = False
    row['requires_video'] = False
    row['requires_note'] = False

    requirements = dict(row.get('execution_requirements') or {})
    requirements.update(
        {
            'gps': False,
            'photo': False,
            'photo_min_count': 0,
            'video': False,
            'video_min_count': 0,
            'video_max_count': 0,
            'note': False,
            'note_required': False,
            'hard_copy_collection': True,
            'custody_submission_required': True,
            'capture_mode': HARD_COPY_CONFIRMATION_SCREEN,
        },
    )
    row['execution_requirements'] = requirements
    return sync_row_evidence_flags(row)


def _hard_pod_blocks_collect_payment(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> bool:
    """Collect Payment is blocked until digital POD + hard-copy custody are complete."""
    if shipment is None:
        return False
    if not _shipment_hard_pod_type(shipment):
        return False
    try:
        flags = pod_cod_policy.derive_pod_cod_flags(
            shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    except Exception:
        return False
    if flags.get('pod_pending'):
        return True
    if flags.get('hard_pod_pending'):
        applicable, block = _hard_copy_applicable(shipment, tenant_schema=tenant_schema)
        if applicable and bool(block.get('pending')):
            return True
    return False


def _apply_redirect_navigation_labels(
    out: dict[str, Any],
    navigation: dict[str, Any],
) -> dict[str, Any]:
    """Keep CTA label aligned with the screen mobile should open."""
    result = dict(out)
    title = str(navigation.get('screen_title') or '').strip()
    if title:
        result['execution_label'] = title
        result['action_name'] = title
    return result


def _collect_payment_pod_redirect(
    event: dict[str, Any],
    *,
    shipment: Any | None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Route Collect Payment taps to the correct POD wizard step when blocked."""
    out = dict(event)
    evidence = dict(log_evidence or {})
    flags = pod_cod_policy.derive_pod_cod_flags(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=evidence,
    )
    if flags.get('pod_pending') and not evidence.get('pod_uploaded'):
        from mobile_api.pod_capture.services.pod_capture_action_resolver import (
            resolve_digital_pod_action,
        )

        digital_action = resolve_digital_pod_action(tenant_schema) if tenant_schema else None
        if digital_action is not None:
            out = apply_pod_upload_navigation(
                out,
                digital_action,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=evidence,
            )
            out = _apply_redirect_navigation_labels(out, out)
            out['redirected_from'] = 'collect_payment'
            out['blocked_reason'] = 'Complete digital POD before collecting payment.'
            return out
    if flags.get('hard_pod_pending') and evidence.get('pod_uploaded'):
        hard_nav = build_hard_copy_navigation_payload(
            shipment,
            tenant_schema=tenant_schema,
            log_evidence=evidence,
        )
        if hard_nav:
            out.update(hard_nav)
            out = _apply_redirect_navigation_labels(out, hard_nav)
            out['redirected_from'] = 'collect_payment'
            out['blocked_reason'] = (
                'Complete hard-copy POD confirmation before collecting payment.'
            )
    return out


def _action_like_from_row(row: dict[str, Any]) -> Any:
    from types import SimpleNamespace

    requirements = dict(row.get('execution_requirements') or {})
    return SimpleNamespace(
        action_code=str(row.get('action_code') or ''),
        english_label=str(
            row.get('action_name')
            or row.get('action_label')
            or row.get('execution_label')
            or row.get('english_label')
            or row.get('label')
            or '',
        ),
        auto_pod_post=bool(requirements.get('auto_pod_post')),
        auto_movement_post=bool(requirements.get('auto_movement_post')),
        auto_shipment_post=bool(requirements.get('auto_shipment_post')),
        auto_treasury_post=bool(requirements.get('auto_treasury_post')),
        hard_copy_collection=bool(requirements.get('hard_copy_collection')),
        shipment_status_impact=str(
            requirements.get('shipment_status_impact')
            or row.get('shipment_status_impact')
            or '',
        ),
        movement_status_impact=str(
            requirements.get('movement_status_impact')
            or row.get('movement_status_impact')
            or '',
        ),
        booking_status_impact=str(
            requirements.get('booking_status_impact')
            or row.get('booking_status_impact')
            or '',
        ),
        sequence_category=str(
            requirements.get('sequence_category')
            or row.get('sequence_category')
            or '',
        ),
        requires_signature=bool(requirements.get('signature')),
        photo_min_count=requirements.get('photo_min_count'),
        video_min_count=requirements.get('video_min_count'),
        video_max_count=requirements.get('video_max_count'),
    )


def _row_is_collect_payment_navigation_target(
    row: dict[str, Any],
    action: Any | None = None,
    *,
    tenant_schema: str = '',
) -> bool:
    if str(row.get('action') or '').strip() == 'go_to_payment_collection':
        return True
    if str(row.get('screen') or '').strip() == 'collect_payment':
        return True
    if str(row.get('ui_mode') or '').strip() == 'collect_payment':
        return True
    act = action or _action_like_from_row(row)
    if action_is_collect_payment(act):
        return True
    if row_is_collect_payment_action(row):
        return True
    code = str(row.get('action_code') or '').strip()
    # Prefer in-memory row/action semantics. Schema lookup is optional and
    # skipped when schema is empty so unit tests stay offline.
    if not (tenant_schema or '').strip():
        return action_code_is_collect_payment(code)
    try:
        return action_code_is_collect_payment(code, tenant_schema=tenant_schema)
    except Exception:
        return action_code_is_collect_payment(code)


def apply_collect_payment_navigation_to_action_row(
    row: dict[str, Any],
    *,
    action: Any | None = None,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Bottom CTA + timeline — open Collect Payment screen (not execute-action)."""
    if not _row_is_collect_payment_navigation_target(
        row,
        action,
        tenant_schema=tenant_schema,
    ):
        return dict(row)
    out = dict(row)
    act = action or _action_like_from_row(row)
    if _hard_pod_blocks_collect_payment(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    ):
        return _collect_payment_pod_redirect(
            out,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    booking = getattr(shipment, 'booking', None)
    # Clear evidence-capture contract so mobile never opens evidence then execute.
    for key in (
        'capture_ui',
        'submit_contract',
        'allow_submit_without_media',
        'show_pod_capture_button',
        'show_close_job_button',
        'pod_capture_steps',
        'hard_copy_confirmation',
        'confirmation_ui',
    ):
        out.pop(key, None)
    requirements = dict(out.get('execution_requirements') or {})
    requirements.update(
        {
            'auto_treasury_post': True,
            'direct_execute': False,
            'requires_evidence_capture': False,
            'capture_mode': 'collect_payment',
            'gps': False,
            'photo_enabled': False,
            'video_enabled': False,
            'note': False,
            'note_required': False,
        },
    )
    out['execution_requirements'] = requirements
    label = str(
        out.get('action_label')
        or out.get('execution_label')
        or out.get('action_name')
        or getattr(act, 'english_label', None)
        or 'Collect Payment',
    ).strip()
    out.update(
        {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'ui_mode': 'collect_payment',
            'screen_title': label or 'Collect Payment',
            'direct_execute': False,
            'requires_evidence_capture': False,
            'requires_gps': False,
            'requires_photo': False,
            'requires_video': False,
            'requires_note': False,
            'show_photo': False,
            'show_video': False,
            'show_note': False,
            'payment_collect_endpoint': PAYMENT_COLLECT_API_PATH,
        },
    )
    out.update(build_cod_payment_display(shipment=shipment, booking=booking))
    return sync_row_evidence_flags(out)


def apply_job_close_navigation_to_action_row(
    row: dict[str, Any],
    *,
    action: Any | None = None,
) -> dict[str, Any]:
    """Timeline / bottom CTA — job close via optional evidence screen."""
    act = action or _action_like_from_row(row)
    if not (action_is_job_close(act) or row_is_job_close_action(row)):
        return dict(row)
    out = dict(row)
    out['ui_mode'] = 'job_close'
    out['screen_title'] = 'Job Close'
    return apply_evidence_capture_navigation_to_action_row(out)


def _targets_empty_move_evidence_capture(
    action: Any | None,
    row: dict[str, Any],
) -> bool:
    act = action or _action_like_from_row(row)
    return (
        is_empty_move_catalog_action(act)
        or action_is_empty_move_lifecycle(act)
        or row_is_empty_move_action(row)
    )


def apply_empty_move_navigation_to_action_row(
    row: dict[str, Any],
    *,
    action: Any | None = None,
) -> dict[str, Any]:
    """Empty-move lifecycle rows — optional evidence before execute."""
    act = action or _action_like_from_row(row)
    if not _targets_empty_move_evidence_capture(act, row):
        return dict(row)
    out = dict(row)
    out['ui_mode'] = 'empty_move'
    label = str(
        out.get('execution_label')
        or out.get('action_name')
        or out.get('label')
        or getattr(act, 'english_label', '')
        or '',
    ).strip()
    if label:
        out['screen_title'] = label
    return apply_evidence_capture_navigation_to_action_row(out)


_COLLECT_PAYMENT_NAV_KEYS = frozenset(
    {
        'action',
        'screen',
        'ui_mode',
        'screen_title',
        'direct_execute',
        'payment_collect_endpoint',
        'amount_due',
        'expected_cod_amount',
        'cod_amount',
        'currency',
        'field_configuration',
        'collection_rules',
        'requires_gps',
        'requires_photo',
        'requires_video',
        'requires_note',
    },
)


def sync_workflow_primary_from_payment_hint(
    workflow: dict[str, Any],
    next_hint: dict[str, Any],
) -> dict[str, Any]:
    """Keep bottom CTA aligned with payment navigation (mobile reads primary_action)."""
    if str(next_hint.get('action') or '') != 'go_to_payment_collection':
        return dict(workflow or {})
    out = dict(workflow or {})

    def _merge_payment_row(row: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(row or {})
        for nav_key in _COLLECT_PAYMENT_NAV_KEYS:
            if nav_key in next_hint:
                merged[nav_key] = next_hint[nav_key]
        if not merged.get('action_code'):
            merged['action_code'] = next_hint.get('action_code')
        if not merged.get('action'):
            merged['action'] = next_hint.get('action')
        if not merged.get('screen'):
            merged['screen'] = next_hint.get('screen')
        label = str(
            merged.get('action_label')
            or merged.get('execution_label')
            or merged.get('action_name')
            or next_hint.get('screen_title')
            or next_hint.get('action_label')
            or 'Collect Payment',
        ).strip()
        merged.setdefault('action_label', label)
        merged.setdefault('execution_label', label)
        merged.setdefault('action_name', label)
        return merged

    for key in ('primary_action', 'next_action'):
        row = dict(out.get(key) or {})
        if _row_is_collect_payment_navigation_target(row):
            out[key] = _merge_payment_row(row)
            continue
        if key == 'primary_action' or not row:
            out[key] = _merge_payment_row(next_hint)
    if not dict(out.get('primary_action') or {}):
        out['primary_action'] = _merge_payment_row(next_hint)
    if not dict(out.get('next_action') or {}):
        out['next_action'] = _merge_payment_row(out['primary_action'])
    return out


_JOB_CLOSE_NAV_KEYS = frozenset(
    {
        'action',
        'screen',
        'ui_mode',
        'screen_title',
        'direct_execute',
        'requires_gps',
        'requires_photo',
        'requires_video',
        'requires_note',
        'action_code',
    },
)


def _hint_targets_job_close_execute(next_hint: dict[str, Any]) -> bool:
    if next_hint.get('show_close_job_button'):
        return True
    if str(next_hint.get('ui_mode') or '') == 'job_close':
        return True
    code = str(next_hint.get('action_code') or '').strip()
    if code and action_code_is_job_close(code):
        return True
    return False


def sync_workflow_primary_from_job_close_hint(
    workflow: dict[str, Any],
    next_hint: dict[str, Any],
) -> dict[str, Any]:
    """Keep bottom CTA aligned with one-tap job close (mobile reads primary_action)."""
    if not _hint_targets_job_close_execute(next_hint):
        return dict(workflow or {})
    nav = apply_job_close_navigation_to_action_row(
        dict(next_hint),
        action=_action_like_from_row(next_hint),
    )
    out = dict(workflow or {})
    for key in ('primary_action', 'next_action'):
        row = dict(out.get(key) or {})
        if row and not row_is_job_close_action(row):
            if key != 'primary_action' or not next_hint.get('show_close_job_button'):
                continue
            merged = dict(nav)
            for label_key in ('label', 'english_label', 'execution_label', 'action_name'):
                if row.get(label_key):
                    merged[label_key] = row[label_key]
            out[key] = merged
            continue
        merged = dict(row) if row else dict(nav)
        for nav_key in _JOB_CLOSE_NAV_KEYS:
            if nav_key in nav:
                merged[nav_key] = nav[nav_key]
        if not merged.get('action_code'):
            merged['action_code'] = nav.get('action_code')
        out[key] = merged
    if not dict(out.get('primary_action') or {}) and next_hint.get('show_close_job_button'):
        out['primary_action'] = dict(nav)
    return out


def _normalize_row_action_labels(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure label fields exist for action-semantics matchers."""
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
        for key in ('action_label', 'english_label', 'action_name', 'execution_label'):
            if not out.get(key):
                out[key] = label
    return out


def _delivery_milestone_blocks_pod_nav_merge(row: dict[str, Any]) -> bool:
    """Never merge POD/hard-copy navigation onto Unloading Completed evidence CTA."""
    normalized = _normalize_row_action_labels(row)
    if str(normalized.get('action') or '').strip() != 'go_to_evidence_capture':
        return False
    if not normalized.get('requires_evidence_capture'):
        return False
    from mobile_api.helpers.job_action_resolver import row_is_unloading_completed_action

    return row_is_unloading_completed_action(normalized)


_POD_CAPTURE_NAV_KEYS = frozenset(
    {
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
        'hard_copy_confirmation',
        'confirmation_ui',
        'documents_endpoint',
        'custody_submit_endpoint',
        'capture_ui',
        'reason',
        'direct_execute',
    },
)


def sync_workflow_primary_from_pod_capture_hint(
    workflow: dict[str, Any],
    next_hint: dict[str, Any],
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Keep bottom CTA aligned with POD capture navigation (mobile reads primary_action)."""
    if str(next_hint.get('action') or '') != 'go_to_pod_capture' and not next_hint.get(
        'show_pod_capture_button',
    ):
        return dict(workflow or {})
    out = dict(workflow or {})
    for key in ('primary_action', 'next_action'):
        row = dict(out.get(key) or {})
        if row and _delivery_milestone_blocks_pod_nav_merge(row):
            out[key] = row
            continue
        if row and not row_has_digital_pod_upload(row):
            if key != 'primary_action':
                continue
            merged: dict[str, Any] = {}
            for label_key in (
                'label',
                'english_label',
                'execution_label',
                'action_name',
            ):
                if row.get(label_key):
                    merged[label_key] = row[label_key]
        else:
            merged = dict(row) if row else {}
        for nav_key in _POD_CAPTURE_NAV_KEYS:
            if nav_key in next_hint:
                merged[nav_key] = next_hint[nav_key]
        if not merged.get('action_code'):
            merged['action_code'] = next_hint.get('action_code')
        if not merged.get('action'):
            merged['action'] = next_hint.get('action')
        merged.pop('requires_evidence_capture', None)
        out[key] = merged
    if not dict(out.get('primary_action') or {}):
        primary = {
            nav_key: next_hint[nav_key]
            for nav_key in _POD_CAPTURE_NAV_KEYS
            if nav_key in next_hint
        }
        if next_hint.get('action_code'):
            primary['action_code'] = next_hint['action_code']
        if next_hint.get('action'):
            primary['action'] = next_hint['action']
        out['primary_action'] = primary
    pod_row = find_pod_upload_row_in_allowed(list(out.get('allowed_actions') or []))
    primary = dict(out.get('primary_action') or {})
    if pod_row:
        for label_key in (
            'action_name',
            'execution_label',
            'english_label',
            'label',
        ):
            if pod_row.get(label_key) and not primary.get(label_key):
                primary[label_key] = pod_row[label_key]
        if pod_row.get('capture_ui') and not primary.get('capture_ui'):
            primary['capture_ui'] = pod_row['capture_ui']
    if primary and not primary.get('capture_ui'):
        primary = _ensure_pod_row_capture_ui(
            primary,
            _action_like_from_row(primary),
            shipment=shipment,
            tenant_schema=tenant_schema,
            has_hard_copy_step=bool(primary.get('hard_pod')),
        )
    if primary:
        out['primary_action'] = primary
        if not dict(out.get('next_action') or {}):
            out['next_action'] = dict(primary)
    return out


_EVIDENCE_CAPTURE_NAV_KEYS = frozenset(
    {
        'action',
        'screen',
        'ui_mode',
        'screen_title',
        'direct_execute',
        'requires_evidence_capture',
        'requires_gps',
        'requires_photo',
        'requires_video',
        'requires_note',
        'show_photo',
        'show_video',
        'show_note',
        'allow_submit_without_media',
        'photo_min_count',
        'video_min_count',
        'execution_requirements',
        'capture_ui',
        'action_code',
    },
)


def _hint_targets_evidence_capture(next_hint: dict[str, Any]) -> bool:
    if str(next_hint.get('action') or '') == GO_TO_EVIDENCE_CAPTURE_ACTION:
        return True
    if str(next_hint.get('screen') or '') == EVIDENCE_CAPTURE_SCREEN:
        return True
    return bool(next_hint.get('requires_evidence_capture'))


def sync_workflow_primary_from_evidence_hint(
    workflow: dict[str, Any],
    next_hint: dict[str, Any],
) -> dict[str, Any]:
    """Keep bottom CTA / primary_action aligned with optional evidence capture metadata."""
    if str(next_hint.get('action') or '').strip() == 'go_to_pod_capture' or next_hint.get(
        'show_pod_capture_button',
    ):
        return dict(workflow or {})
    primary = dict((workflow or {}).get('primary_action') or {})
    if str(primary.get('action') or '').strip() == 'go_to_pod_capture':
        return dict(workflow or {})
    if not _hint_targets_evidence_capture(next_hint):
        return dict(workflow or {})
    nav = apply_evidence_capture_navigation_to_action_row(dict(next_hint))
    out = dict(workflow or {})
    for key in ('primary_action', 'next_action'):
        row = dict(out.get(key) or {})
        if not row:
            if key == 'primary_action':
                out[key] = dict(nav)
            continue
        code = str(row.get('action_code') or '').strip().casefold()
        nav_code = str(nav.get('action_code') or '').strip().casefold()
        if code and nav_code and code != nav_code and key != 'primary_action':
            continue
        merged = dict(row)
        for nav_key in _EVIDENCE_CAPTURE_NAV_KEYS:
            if nav_key in nav:
                merged[nav_key] = nav[nav_key]
        if not merged.get('action_code'):
            merged['action_code'] = nav.get('action_code')
        out[key] = merged
    if not dict(out.get('primary_action') or {}):
        out['primary_action'] = dict(nav)
    return out


def sync_workflow_primary_from_next_hint(
    workflow: dict[str, Any],
    next_hint: dict[str, Any],
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Align workflow CTAs with ``next_action_hint`` navigation contract."""
    out = sync_workflow_primary_from_payment_hint(workflow, next_hint)
    out = sync_workflow_primary_from_job_close_hint(out, next_hint)
    out = sync_workflow_primary_from_pod_capture_hint(
        out,
        next_hint,
        shipment=shipment,
        tenant_schema=tenant_schema,
    )
    return sync_workflow_primary_from_evidence_hint(out, next_hint)


def finalize_timeline_preview_navigation(
    events: list[dict[str, Any]] | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Re-apply navigation metadata on pending timeline rows (job detail + timeline API)."""
    if not events:
        return []
    preview = list(events)
    out: list[dict[str, Any]] = []
    for event in preview:
        if not isinstance(event, dict):
            continue
        row = dict(event)
        if str(row.get('authority') or '') == 'action_log':
            out.append(row)
            continue
        if row.get('is_performed') or str(row.get('timeline_state') or '') == 'performed':
            out.append(row)
            continue
        action = _action_like_from_row(row)
        row = enrich_timeline_event_navigation(
            row,
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
            timeline_preview=preview,
        )
        out.append(row)
    return out


def _enrich_driver_action_row(
    row: dict[str, Any],
    *,
    action: Any | None,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Apply navigation contract for one workflow / timeline row."""
    if not row:
        return row
    action = action or _action_like_from_row(row)
    from mobile_api.helpers.job_action_resolver import row_is_unloading_completed_action

    normalized = _normalize_row_action_labels(row)
    if row_is_unloading_completed_action(normalized):
        return apply_evidence_capture_navigation_to_action_row(dict(row))
    if _row_is_collect_payment_navigation_target(
        row,
        action,
        tenant_schema=tenant_schema,
    ):
        return apply_collect_payment_navigation_to_action_row(
            dict(row),
            action=action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    if action_is_job_close(action) or row_is_job_close_action(row):
        return apply_job_close_navigation_to_action_row(
            dict(row),
            action=action,
        )
    if _targets_empty_move_evidence_capture(action, row):
        return apply_empty_move_navigation_to_action_row(
            dict(row),
            action=action,
        )
    if str(row.get('action') or '').strip() == 'go_to_pod_capture':
        if not is_pod_upload_action(action):
            action = _action_like_from_row(row)
        return apply_pod_upload_navigation(
            dict(row),
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    if is_without_scope_action(action) or row_is_without_scope_action(row):
        return apply_standalone_evidence_capture_navigation_to_action_row(
            dict(row),
            action=action,
        )
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        row_has_digital_pod_upload,
    )

    if is_pod_upload_action(action) or row_has_digital_pod_upload(row):
        if not is_pod_upload_action(action):
            action = _action_like_from_row(row)
        return apply_pod_upload_navigation(
            dict(row),
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    if is_hard_copy_only_navigation_action(action):
        return apply_hard_copy_navigation_to_action_row(
            dict(row),
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    return apply_evidence_capture_navigation_to_action_row(dict(row))


def enrich_workflow_pod_navigation(
    workflow: dict[str, Any],
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Align allowed-action navigation with log-aware POD/COD flags."""
    out = dict(workflow or {})
    evidence = dict(log_evidence or {})

    def _enrich_row(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return row
        action = _action_like_from_row(row)
        return _enrich_driver_action_row(
            dict(row),
            action=action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=evidence,
        )

    out['allowed_actions'] = [
        _enrich_row(dict(row)) for row in (out.get('allowed_actions') or [])
    ]
    for key in ('primary_action', 'next_action'):
        row = dict(out.get(key) or {})
        if row:
            out[key] = _enrich_row(row)
    return out


def enrich_timeline_event_navigation(
    event: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
    timeline_preview: list[Any] | None = None,
) -> dict[str, Any]:
    """Attach navigation hints to timeline rows (performed or pending)."""
    if str(event.get('authority') or '') == 'action_log':
        return dict(event)
    if str(event.get('timeline_state') or '') == 'performed' or event.get('is_performed'):
        return dict(event)
    if is_hard_copy_only_navigation_action(action):
        navigation = build_hard_copy_navigation_payload(
            shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
        if not navigation:
            return dict(event)
        out = dict(event)
        out.update(navigation)
        out['screen'] = POD_CAPTURE_SCREEN
        out['action'] = 'go_to_pod_capture'
        out['capture_mode'] = HARD_COPY_CONFIRMATION_SCREEN
        out['active_step'] = 'hard_copy_confirmation'
        return out
    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )
    from mobile_api.pod_capture.services.pod_capture_action_resolver import (
        timeline_pod_step_is_actionable,
    )

    if is_pod_upload_action(action):
        if not timeline_pod_step_is_actionable(
            dict(event),
            shipment=shipment,
            timeline_preview=timeline_preview,
        ):
            out = dict(event)
            for key in (
                'action',
                'screen',
                'capture_ui',
                'capture_mode',
                'active_step',
                'ui_mode',
                'screen_title',
                'pod_capture_steps',
                'hard_pod',
                'includes_hard_copy',
                'show_pod_capture_button',
                'requires_evidence_capture',
                'direct_execute',
            ):
                out.pop(key, None)
            return out
    return _enrich_driver_action_row(
        dict(event),
        action=action,
        shipment=shipment,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
