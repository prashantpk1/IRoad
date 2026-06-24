"""
Mobile navigation metadata for Action Master rows (timeline taps, allowed actions).

Upload POD (A7 / OA-0008): digital evidence first; hard-copy checklist second when
``pod_type`` is Hard and delivery-note custody applies.

Hard-copy-only rows (A7H): custody checklist only — no digital wizard.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.cod_amount import build_cod_payment_display
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
)

HARD_COPY_CONFIRMATION_SCREEN = 'hard_copy_confirmation'
POD_CAPTURE_SCREEN = 'pod_capture'
DIGITAL_EVIDENCE_SCREEN = 'digital_evidence'


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


def _digital_pod_complete(
    shipment: Any | None,
    *,
    log_evidence: dict[str, bool] | None = None,
    tenant_schema: str = '',
) -> bool:
    if shipment is None:
        return False
    evidence = log_evidence or {}
    if evidence.get('pod_uploaded'):
        return True
    flags = pod_cod_policy.derive_pod_cod_flags(
        shipment,
        log_evidence=evidence,
        tenant_schema=tenant_schema,
    )
    return bool(flags.get('pod_compliant')) and not bool(flags.get('pod_pending'))


def _hard_copy_applicable(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
) -> tuple[bool, dict[str, Any]]:
    if not _shipment_hard_pod_type(shipment):
        return False, {}
    block = build_hard_copy_confirmation_block(
        shipment,
        tenant_schema=tenant_schema,
    )
    applicable = bool(block.get('required') or block.get('applicable'))
    return applicable, block


def build_hard_copy_navigation_payload(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """Checklist contract for Hard POD Collection Confirmation UI."""
    applicable, block = _hard_copy_applicable(shipment, tenant_schema=tenant_schema)
    if not applicable or not block.get('pending'):
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
    if not is_pod_upload_action(action):
        return row

    hard_applicable, hard_block = _hard_copy_applicable(
        shipment,
        tenant_schema=tenant_schema,
    )
    digital_complete = _digital_pod_complete(
        shipment,
        log_evidence=log_evidence,
        tenant_schema=tenant_schema,
    )

    if digital_complete and hard_applicable and bool(hard_block.get('pending')):
        navigation = build_hard_copy_navigation_payload(
            shipment,
            tenant_schema=tenant_schema,
        )
        if navigation:
            out = dict(row)
            out.update(navigation)
            out['pod_capture_steps'] = build_pod_capture_steps(hard_pod=True)
            return out

    capture_steps = build_pod_capture_steps(
        hard_pod=hard_applicable and bool(hard_block.get('pending')),
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
            'hard_pod': hard_applicable,
            'includes_hard_copy': hard_applicable,
            'requires_gps': False,
            'requires_photo': True,
            'requires_video': False,
            'requires_note': False,
        },
    )
    if hard_applicable:
        out['hard_copy_confirmation'] = hard_block
        if hard_block.get('confirmation_ui') and hard_block.get('pending'):
            out['confirmation_ui'] = dict(hard_block['confirmation_ui'])
    if capture_ui:
        out['capture_ui'] = capture_ui
    return out


def apply_hard_copy_navigation_to_action_row(
    row: dict[str, Any],
    action: Any | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
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
        )
    if not is_hard_copy_only_navigation_action(action):
        return row

    navigation = build_hard_copy_navigation_payload(
        shipment,
        tenant_schema=tenant_schema,
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
    return row


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
    if flags.get('hard_pod_pending'):
        hard_nav = build_hard_copy_navigation_payload(
            shipment,
            tenant_schema=tenant_schema,
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
            or row.get('execution_label')
            or row.get('english_label')
            or row.get('label')
            or '',
        ),
        auto_pod_post=bool(requirements.get('auto_pod_post')),
        auto_treasury_post=bool(requirements.get('auto_treasury_post')),
        hard_copy_collection=bool(requirements.get('hard_copy_collection')),
        shipment_status_impact=str(
            requirements.get('shipment_status_impact')
            or row.get('shipment_status_impact')
            or '',
        ),
    )


def _row_is_collect_payment_navigation_target(
    row: dict[str, Any],
    action: Any | None = None,
) -> bool:
    act = action or _action_like_from_row(row)
    if action_is_collect_payment(act):
        return True
    if row_is_collect_payment_action(row):
        return True
    code = str(row.get('action_code') or '').strip()
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
    if not _row_is_collect_payment_navigation_target(row, action):
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
    out.update(
        {
            'action': 'go_to_payment_collection',
            'screen': 'collect_payment',
            'ui_mode': 'collect_payment',
            'screen_title': 'Collect Payment',
            'direct_execute': False,
            'requires_gps': False,
            'requires_photo': False,
            'requires_video': False,
            'requires_note': False,
            'payment_collect_endpoint': PAYMENT_COLLECT_API_PATH,
        },
    )
    out.update(build_cod_payment_display(shipment=shipment, booking=booking))
    return out


def apply_job_close_navigation_to_action_row(
    row: dict[str, Any],
    *,
    action: Any | None = None,
) -> dict[str, Any]:
    """Timeline / bottom CTA — one-tap job close on Job Detail."""
    act = action or _action_like_from_row(row)
    if not (action_is_job_close(act) or row_is_job_close_action(row)):
        return dict(row)
    out = dict(row)
    out.update(
        {
            'action': 'execute_action',
            'screen': 'job_detail',
            'ui_mode': 'job_close',
            'screen_title': 'Job Close',
            'direct_execute': True,
            'requires_gps': False,
            'requires_photo': False,
            'requires_video': False,
            'requires_note': False,
        },
    )
    return out


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
    for key in ('primary_action', 'next_action'):
        row = dict(out.get(key) or {})
        if not _row_is_collect_payment_navigation_target(row):
            continue
        merged = dict(row)
        for nav_key in _COLLECT_PAYMENT_NAV_KEYS:
            if nav_key in next_hint:
                merged[nav_key] = next_hint[nav_key]
        out[key] = merged
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
    return str(next_hint.get('action') or '') == 'execute_action' and bool(
        next_hint.get('direct_execute'),
    ) and bool(code)


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


def sync_workflow_primary_from_next_hint(
    workflow: dict[str, Any],
    next_hint: dict[str, Any],
) -> dict[str, Any]:
    """Align workflow CTAs with ``next_action_hint`` navigation contract."""
    out = sync_workflow_primary_from_payment_hint(workflow, next_hint)
    return sync_workflow_primary_from_job_close_hint(out, next_hint)


def finalize_timeline_preview_navigation(
    events: list[dict[str, Any]] | None,
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Re-apply payment navigation on pending timeline rows (timeline API + job detail)."""
    if not events:
        return []
    out: list[dict[str, Any]] = []
    for event in events:
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
        if _row_is_collect_payment_navigation_target(row, action):
            row = apply_collect_payment_navigation_to_action_row(
                row,
                action=action,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=log_evidence,
            )
        elif action_is_job_close(action) or row_is_job_close_action(row):
            row = apply_job_close_navigation_to_action_row(row, action=action)
        out.append(row)
    return out


def enrich_workflow_pod_navigation(
    workflow: dict[str, Any],
    *,
    shipment: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Align allowed-action navigation with log-aware POD/COD flags."""
    if shipment is None:
        return dict(workflow or {})

    out = dict(workflow or {})
    evidence = dict(log_evidence or {})

    def _enrich_row(row: dict[str, Any]) -> dict[str, Any]:
        if not row:
            return row
        action = _action_like_from_row(row)
        if _row_is_collect_payment_navigation_target(row, action):
            return apply_collect_payment_navigation_to_action_row(
                dict(row),
                action=action,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=evidence,
            )
        if action_is_job_close(action) or row_is_job_close_action(row):
            return apply_job_close_navigation_to_action_row(
                dict(row),
                action=action,
            )
        if is_pod_upload_action(action):
            return apply_pod_upload_navigation(
                dict(row),
                action,
                shipment=shipment,
                tenant_schema=tenant_schema,
                log_evidence=evidence,
            )
        if is_hard_copy_only_navigation_action(action):
            return apply_hard_copy_navigation_to_action_row(
                dict(row),
                action,
                shipment=shipment,
                tenant_schema=tenant_schema,
            )
        return dict(row)

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
) -> dict[str, Any]:
    """Attach navigation hints to timeline rows (performed or pending)."""
    if str(event.get('authority') or '') == 'action_log':
        return dict(event)
    if _row_is_collect_payment_navigation_target(event, action):
        return apply_collect_payment_navigation_to_action_row(
            event,
            action=action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    if action_is_job_close(action) or row_is_job_close_action(event):
        return apply_job_close_navigation_to_action_row(event, action=action)
    if is_hard_copy_only_navigation_action(action):
        navigation = build_hard_copy_navigation_payload(
            shipment,
            tenant_schema=tenant_schema,
        )
        if not navigation:
            return event
        out = dict(event)
        out.update(navigation)
        out['screen'] = POD_CAPTURE_SCREEN
        out['action'] = 'go_to_pod_capture'
        out['capture_mode'] = HARD_COPY_CONFIRMATION_SCREEN
        out['active_step'] = 'hard_copy_confirmation'
        return out
    if is_pod_upload_action(action):
        return apply_pod_upload_navigation(
            dict(event),
            action,
            shipment=shipment,
            tenant_schema=tenant_schema,
            log_evidence=log_evidence,
        )
    return event
