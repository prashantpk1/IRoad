"""
mobile_api/pod_capture/services/pod_section_metadata.py

POD-section-only metadata (digital evidence + hard-copy confirmation).

Hard POD confirmation is exposed here — not on dashboard alerts or global
next-action hints. Job Detail ``pod_cod`` keeps flags only; pages live here.
"""
from __future__ import annotations

from typing import Any

from django_tenants.utils import schema_context

from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.helpers.evidence_requirement_flags import normalize_evidence_requirements
from mobile_api.execution.evidence.constants import (
    POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
)
from mobile_api.hard_pod.services.delivery_note_pages import (
    build_hard_pod_confirmation_context,
)
from mobile_api.pod_capture.policy.pod_capture_policy import (
    build_pod_capture_requirements,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
    CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE,
    HARD_POD_ACTION_CODE,
    POD_DIGITAL_ACTION_CODE,
    action_code_from_action,
    resolve_digital_pod_action,
    resolve_digital_pod_action_code,
    resolve_hard_copy_pod_action,
)
from tenant_workspace.models import TenantShipment
HARD_COPY_SCREEN_TITLE = 'Hard POD Collection Confirmation'
DIGITAL_EVIDENCE_SCREEN_TITLE = 'Capturing Action Evidences'
UI_MODE_HARD_POD_CONFIRMATION = 'hard_pod_collection_confirmation'
UI_MODE_DIGITAL_EVIDENCE = 'digital_evidence'

# Mobile wizard step ids (``pod_capture_steps``) — same tokens as ``capture_mode`` / ``active_step``.
POD_CAPTURE_STEP_DIGITAL = 'digital_evidence'
POD_CAPTURE_STEP_HARD_COPY = 'hard_copy_confirmation'


def build_pod_capture_steps(*, hard_pod: bool) -> list[str]:
    """Step order for Upload POD: digital always first; hard copy second when Hard POD."""
    if hard_pod:
        return [POD_CAPTURE_STEP_DIGITAL, POD_CAPTURE_STEP_HARD_COPY]
    return [POD_CAPTURE_STEP_DIGITAL]


def _shipment_has_delivery_note(shipment: Any | None, *, tenant_schema: str) -> bool:
    """Hard-copy confirmation requires a portal Shipment Document (DN flag may be true or false)."""
    schema = (tenant_schema or '').strip()
    if shipment is None or not schema:
        return False
    try:
        with schema_context(schema):
            from tenant_workspace.models import TenantShipmentDocument

            shipment_pk = getattr(shipment, 'pk', None)
            if TenantShipmentDocument.objects.filter(shipment_id=shipment_pk).exclude(
                document_type__iexact='pod',
            ).exists():
                return True
            booking_id = getattr(shipment, 'booking_id', None)
            if booking_id:
                return TenantShipmentDocument.objects.filter(booking_id=booking_id).exclude(
                    document_type__iexact='pod',
                ).exists()
            return False
    except Exception:
        return False


def build_hard_copy_confirmation_ui(
    pages: list[dict[str, Any]],
    *,
    execute_action_code: str = '',
) -> dict[str, Any]:
    """
    Mobile layout for Hard POD Collection Confirmation (checkbox custody checklist).

    Not the digital evidence screen — no photo / video / GPS capture sections.
    """
    checklist: list[dict[str, Any]] = []
    for page in pages:
        line_no = int(page.get('line_no') or page.get('physical_page_no') or 1)
        checklist.append(
            {
                'page_id': str(page.get('page_id') or ''),
                'document_id': str(page.get('document_id') or ''),
                'line_no': line_no,
                'label': str(page.get('label') or f'Page-{line_no}'),
                'confirmation_text': str(
                    page.get('confirmation_text')
                    or (
                        f'I confirm the physical receipt of this original '
                        f'document of {line_no}'
                    )
                ),
                'required': True,
            },
        )
    return {
        'ui_mode': UI_MODE_HARD_POD_CONFIRMATION,
        'screen_type': 'custody_checklist',
        'screen_title': HARD_COPY_SCREEN_TITLE,
        'info_banner': {
            'title': 'Physical Custody Confirmation',
            'subtitle': (
                'Drivers must explicitly confirm they have collected '
                'the physical signed papers.'
            ),
        },
        'checklist': checklist,
        'requires_gps': False,
        'requires_photo': False,
        'requires_video': False,
        'requires_note': False,
        'footer_hint': 'Upload every mandatory signed document page.',
        'primary_button': {
            'label': 'Submit POD',
            'action': 'submit_hard_pod_custody',
            'requires_execute_action': True,
            'execute_action_code': (
                execute_action_code or CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE
            ),
            'complete_upload_after_execute': True,
        },
    }


def build_digital_capture_ui(
    requirements: dict[str, Any],
    *,
    has_hard_copy_step: bool = False,
    allow_hard_copy_wizard_next: bool = False,
    digital_action_code: str = CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
) -> dict[str, Any]:
    """Mobile layout contract for Layer-1 digital evidence (Capturing Action Evidences)."""
    from mobile_api.execution.evidence.evidence_capture_ui import (
        build_media_evidence_sections,
    )

    req = normalize_evidence_requirements(requirements)
    video_max_seconds = int(
        req.get('video_max_duration_seconds') or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    )
    photo_min = int(req.get('photo_min_count') or 0)
    video_min = int(req.get('video_min_count') or 0)
    photo_required = photo_min > 0
    video_required = video_min > 0
    allow_empty = bool(req.get('allow_submit_without_media'))
    sections = build_media_evidence_sections(req, include_note=True)
    return {
        'ui_mode': UI_MODE_DIGITAL_EVIDENCE,
        'screen_title': DIGITAL_EVIDENCE_SCREEN_TITLE,
        'show_photo': True,
        'show_video': True,
        'requires_photo': False,
        'requires_video': False,
        'photo_optional': True,
        'photo_mandatory': False,
        'video_optional': True,
        'video_mandatory': False,
        'video_max_duration_seconds': video_max_seconds,
        'allow_submit_without_media': allow_empty,
        'gps_banner': {
            'label': 'GPS captured + Evidence Media',
            'subtitle': f'Video clips must be max {video_max_seconds} seconds.',
        },
        'sections': sections,
        'footer_hint': (
            'Photos and videos are optional. Tap Next to continue without media.'
            if allow_empty
            else 'Upload every mandatory signed document page.'
        ),
        'submit_validation': {
            'photo_min_count': photo_min,
            'video_min_count': video_min,
            'photo_required': photo_required,
            'video_required': video_required,
            'video_max_count': int(req.get('video_max_count') or 0) or 1,
            'video_max_duration_seconds': video_max_seconds,
            'allow_empty_media': allow_empty,
        },
        'primary_button': _build_digital_primary_button(
            has_hard_copy_step,
            digital_action_code=digital_action_code,
            allow_hard_copy_wizard_next=allow_hard_copy_wizard_next,
        ),
    }


def _apply_shipment_document_gate_to_capture_ui(
    capture_ui: dict[str, Any],
    document_gate: dict[str, Any],
) -> dict[str, Any]:
    """Block digital Next and surface portal document message on the evidence screen."""
    ui = dict(capture_ui or {})
    message = (document_gate.get('message') or '').strip()
    if not message:
        return ui
    ui['submit_blocked'] = True
    ui['submit_blocked_reason'] = message
    ui['shipment_document_required'] = True
    ui['shipment_document_ready'] = False
    ui['shipment_document_message'] = message
    primary = dict(ui.get('primary_button') or {})
    primary['disabled'] = True
    primary.pop('wizard_next_step', None)
    primary['complete_upload_after_execute'] = True
    primary['hard_copy_blocked'] = True
    primary['hard_copy_blocked_reason'] = message
    ui['primary_button'] = primary
    return ui


def _build_digital_primary_button(
    has_hard_copy_step: bool,
    *,
    digital_action_code: str,
    allow_hard_copy_wizard_next: bool = False,
) -> dict[str, Any]:
    """
    Digital screen ends with Next — not Submit POD.

    Hard POD: Next → execute tenant POD action → hard-copy wizard step only when
    a portal Shipment Document exists (``allow_hard_copy_wizard_next``).
    Soft / no DN: Next → execute tenant POD action → Upload POD complete.
    """
    button: dict[str, Any] = {
        'label': 'Next',
        'action': 'submit_digital_evidence',
        'execute_action_code': digital_action_code,
        'allow_empty_media': True,
        'photo_required': False,
        'video_required': False,
        'requires_photo': False,
        'requires_video': False,
    }
    if allow_hard_copy_wizard_next:
        button['wizard_next_step'] = 'hard_copy_confirmation'
        button['complete_upload_after_execute'] = False
    elif has_hard_copy_step:
        button['hard_copy_blocked'] = True
        from iroad_tenants.operation_runtime.pod_action import POD_REQUIRES_SHIPMENT_DOCUMENT_MSG

        button['hard_copy_blocked_reason'] = POD_REQUIRES_SHIPMENT_DOCUMENT_MSG
        button['complete_upload_after_execute'] = True
    else:
        button['complete_upload_after_execute'] = True
    return button


def _build_digital_media_steps(requirements: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered capture slots for mobile Upload POD (digital evidence layer)."""
    steps: list[dict[str, Any]] = []
    req = normalize_evidence_requirements(requirements)
    photo_min = int(req.get('photo_min_count') or 0)
    photo_required = photo_min > 0
    if bool(req.get('photo_enabled')) or photo_min > 0 or not photo_required:
        steps.append(
            {
                'media_type': 'photo',
                'required': photo_required,
                'optional': not photo_required,
                'min_count': photo_min,
                'max_count': max(photo_min, 1) if photo_min > 0 else int(
                    requirements.get('photo_max_count') or 0
                ) or 1,
                'label': 'Delivery note photo',
                'skippable': True,
                'enforce_min_count': False,
            }
        )
    if bool(requirements.get('signature')):
        steps.append(
            {
                'media_type': 'signature',
                'required': True,
                'min_count': 1,
                'max_count': 1,
                'label': 'Customer signature',
            }
        )
    video_min = int(req.get('video_min_count') or 0)
    video_required = video_min > 0
    video_optional = bool(req.get('video_optional')) or not video_required
    if bool(req.get('video_enabled')) or video_required or video_optional:
        steps.append(
            {
                'media_type': 'video',
                'required': video_required,
                'optional': video_optional,
                'min_count': video_min,
                'max_count': max(int(req.get('video_max_count') or 0), 1),
                'max_duration_seconds': int(
                    req.get('video_max_duration_seconds')
                    or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
                ),
                'label': 'Delivery video',
                'skippable': True,
                'enforce_min_count': False,
            }
        )
    return steps


def build_digital_evidence_block(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    has_hard_copy_step: bool = False,
    allow_hard_copy_wizard_next: bool = False,
) -> dict[str, Any]:
    """
    Layer-1 digital capture contract (GPS / photo / signature / video for auto_pod_post).
    """
    schema = (tenant_schema or '').strip()
    action = resolve_digital_pod_action(schema) if schema else None
    digital_action_code = action_code_from_action(
        action,
        fallback=CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
    )
    requirements = build_pod_capture_requirements(
        action,
        pod_capture_type='digital',
        shipment=shipment,
    )
    requirement_payload = {
        'gps': bool(requirements.get('gps')),
        'photo_enabled': bool(requirements.get('photo_enabled')),
        'photo': bool(requirements.get('photo')),
        'photo_min_count': int(requirements.get('photo_min_count') or 0),
        'video_enabled': bool(requirements.get('video_enabled')),
        'video': bool(requirements.get('video')),
        'video_optional': bool(requirements.get('video_optional')),
        'video_min_count': int(requirements.get('video_min_count') or 0),
        'video_max_count': int(requirements.get('video_max_count') or 0),
        'video_max_duration_seconds': int(
            requirements.get('video_max_duration_seconds')
            or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
        ),
        'signature': bool(requirements.get('signature')),
        'note': bool(requirements.get('note')),
        'note_required': bool(requirements.get('note_required')),
        'auto_pod_post': bool(requirements.get('auto_pod_post')),
        'allow_submit_without_media': bool(requirements.get('allow_submit_without_media')),
    }
    return {
        'action_code': digital_action_code,
        'execute_action_code': digital_action_code,
        'requirements': requirement_payload,
        'media_steps': _build_digital_media_steps(requirement_payload),
        'capture_mode': 'digital_evidence',
        'screen_title': 'Capturing Action Evidences',
        'capture_ui': build_digital_capture_ui(
            requirement_payload,
            has_hard_copy_step=has_hard_copy_step,
            allow_hard_copy_wizard_next=allow_hard_copy_wizard_next,
            digital_action_code=digital_action_code,
        ),
    }


def _hard_copy_confirmation_actionable(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> bool:
    """Hard-copy checklist only after digital POD log and portal Shipment Document."""
    evidence = log_evidence or {}
    if not evidence.get('pod_uploaded'):
        return False
    schema = (tenant_schema or '').strip()
    if pod_cod_policy.is_hard_pod_custody_complete(
        shipment,
        log_evidence=evidence,
        tenant_schema=schema,
    ):
        return False
    return _shipment_has_delivery_note(shipment, tenant_schema=schema)


def _shipment_hard_pod_type(shipment: Any | None) -> bool:
    if shipment is None:
        return False
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    if pod_type == TenantShipment.PodType.HARD.casefold():
        return True
    booking = getattr(shipment, 'booking', None)
    if booking is not None:
        booking_pod = (getattr(booking, 'pod_type', None) or '').strip().casefold()
        if booking_pod == TenantShipment.PodType.HARD.casefold():
            return True
    return False


def _hard_pod_wizard_includes_hard_copy_step(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> bool:
    """Step-2 metadata for Upload POD wizard (digital always opens first)."""
    if not _shipment_hard_pod_type(shipment):
        return False
    return pod_cod_policy.hard_pod_stage_reached(
        shipment,
        log_evidence=log_evidence,
    )


def _shipment_hard_copy_applicable(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
    dn_pages: list[dict[str, Any]] | None = None,
) -> bool:
    """Hard-copy confirmation UI — requires portal Shipment Document, not synthetic pages."""
    _ = dn_pages
    if shipment is None:
        return False
    if not _shipment_hard_pod_type(shipment):
        return False
    shipment_status = (getattr(shipment, 'shipment_status', None) or '').strip()
    if shipment_status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }:
        return False
    schema = (tenant_schema or '').strip()
    if not _shipment_has_delivery_note(shipment, tenant_schema=schema):
        return False
    return pod_cod_policy.hard_pod_stage_reached(
        shipment,
        log_evidence=log_evidence,
    )


def build_hard_copy_confirmation_block(
    shipment: Any | None,
    *,
    driver: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Hard POD checklist + submit contract (shared by POD section, workflow, timeline).
    """
    _ = driver
    if shipment is None:
        return _empty_hard_copy_block()

    schema = (tenant_schema or '').strip()
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()

    def _derive_pending() -> bool:
        if schema:
            with schema_context(schema):
                return pod_cod_policy.derive_hard_pod_pending(
                    shipment,
                    log_evidence=log_evidence,
                    tenant_schema=schema,
                )
        return pod_cod_policy.derive_hard_pod_pending(
            shipment,
            log_evidence=log_evidence,
            tenant_schema=schema,
        )

    hard_pod_pending = _derive_pending()
    custody_complete = False
    if schema:
        with schema_context(schema):
            custody_complete = pod_cod_policy.is_hard_pod_custody_complete(
                shipment,
                log_evidence=log_evidence,
                tenant_schema=schema,
            )
    else:
        custody_complete = pod_cod_policy.is_hard_pod_custody_complete(
            shipment,
            log_evidence=log_evidence,
            tenant_schema=schema,
        )
    if custody_complete:
        hard_pod_pending = False

    pod_type_hard = pod_type == TenantShipment.PodType.HARD.casefold()
    confirmation_context = (
        build_hard_pod_confirmation_context(
            shipment,
            tenant_schema=schema,
        )
        if pod_type_hard
        else {'documents': [], 'pages': []}
    )
    pages = list(confirmation_context.get('pages') or [])
    applicable = _shipment_hard_copy_applicable(
        shipment,
        tenant_schema=schema,
        log_evidence=log_evidence,
        dn_pages=pages,
    )
    actionable = applicable and _hard_copy_confirmation_actionable(
        shipment,
        tenant_schema=schema,
        log_evidence=log_evidence,
    )
    if custody_complete:
        applicable = False
        actionable = False
        pages = []
        confirmation_context = {'documents': [], 'pages': []}
    shipment_pk = getattr(shipment, 'pk', '')
    hard_copy_action = resolve_hard_copy_pod_action(schema) if schema else None
    from mobile_api.hard_pod.services.hard_pod_custody_promotion import (
        resolve_hard_pod_promotion_action_code,
    )

    hard_copy_action_code = resolve_hard_pod_promotion_action_code(
        schema,
        shipment=shipment,
        fallback=action_code_from_action(
            hard_copy_action,
            fallback=(
                resolve_digital_pod_action_code(schema)
                if schema
                else CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE
            ),
        ),
    )
    if not applicable or not actionable:
        pages = []
        confirmation_context = {'documents': [], 'pages': []}

    block: dict[str, Any] = {
        'applicable': applicable,
        'actionable': actionable,
        'required': applicable,
        'submit_allowed': actionable and hard_pod_pending,
        'pending': hard_pod_pending if applicable else False,
        'documents_source': 'shipment_document' if applicable else '',
        'action_code': hard_copy_action_code if applicable else '',
        'documents': list(confirmation_context.get('documents') or []),
        'pages': pages,
        'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
        'documents_endpoint': (
            f'/api/v1/mobile/driver/jobs/shipments/{shipment_pk}/hard-pod/documents/'
            if applicable
            else ''
        ),
        'execute_action_code': hard_copy_action_code,
        'ui_mode': UI_MODE_HARD_POD_CONFIRMATION if applicable else '',
        'screen_title': HARD_COPY_SCREEN_TITLE if applicable else '',
    }
    if applicable and pages and actionable:
        from iroad_tenants.operation_runtime.pod_action import build_shipment_document_gate

        document_gate = build_shipment_document_gate(shipment, tenant_schema=schema)
        block['confirmation_ui'] = build_hard_copy_confirmation_ui(
            pages,
            execute_action_code=hard_copy_action_code,
        )
        if document_gate.get('message'):
            ui = dict(block['confirmation_ui'])
            ui['submit_blocked'] = True
            ui['submit_blocked_reason'] = document_gate['message']
            primary = dict(ui.get('primary_button') or {})
            primary['disabled'] = True
            ui['primary_button'] = primary
            block['confirmation_ui'] = ui
            block['submit_allowed'] = False
            block['shipment_document_required'] = True
            block['shipment_document_ready'] = False
            block['shipment_document_message'] = document_gate['message']
    return block


def build_pod_section_metadata(
    shipment: Any | None,
    *,
    driver: Any | None = None,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """
    Metadata for the Upload POD mobile section only.

    Mobile should render ``hard_copy_confirmation`` only inside the POD flow
    (``GET/POST .../pod/capture/``), not from dashboard or job-level hints.
    """
    if shipment is None:
        return _empty_pod_section()

    evidence = log_evidence or {}
    hard_copy_block = build_hard_copy_confirmation_block(
        shipment,
        driver=driver,
        tenant_schema=tenant_schema,
        log_evidence=log_evidence,
    )
    hard_copy_applicable = bool(hard_copy_block.get('applicable'))
    hard_wizard_step = _hard_pod_wizard_includes_hard_copy_step(
        shipment,
        tenant_schema=tenant_schema,
        log_evidence=evidence,
    )
    steps = build_pod_capture_steps(hard_pod=hard_wizard_step)

    allow_wizard_next = bool(hard_copy_block.get('applicable'))
    digital_block = build_digital_evidence_block(
        shipment,
        tenant_schema=tenant_schema,
        has_hard_copy_step=hard_wizard_step,
        allow_hard_copy_wizard_next=allow_wizard_next,
    )
    digital_complete = bool(evidence.get('pod_uploaded'))
    from mobile_api.helpers.hard_copy_workflow_gate import derive_unloading_pending
    from iroad_tenants.operation_runtime.pod_action import build_shipment_document_gate

    schema = (tenant_schema or '').strip()
    digital_action = resolve_digital_pod_action(schema) if schema else None
    document_gate = build_shipment_document_gate(
        shipment,
        action=digital_action,
        tenant_schema=schema,
    )
    capture_ui = dict(digital_block.get('capture_ui') or {})
    if document_gate.get('message'):
        capture_ui = _apply_shipment_document_gate_to_capture_ui(capture_ui, document_gate)

    return {
        'pod_type': (getattr(shipment, 'pod_type', None) or '').strip(),
        'pod_doc_count': int(getattr(shipment, 'pod_doc_count', None) or 0),
        'hard_pod_pending': bool(hard_copy_block.get('pending')),
        'digital_evidence_complete': digital_complete,
        'unloading_pending': derive_unloading_pending(shipment),
        'shipment_document_required': bool(document_gate.get('required')),
        'shipment_document_ready': bool(document_gate.get('ready')),
        'shipment_document_message': document_gate.get('message') or '',
        'capture_steps': steps,
        'digital_evidence': digital_block,
        'hard_copy_confirmation': hard_copy_block,
        'screen_title': digital_block.get('screen_title') or DIGITAL_EVIDENCE_SCREEN_TITLE,
        'capture_ui': capture_ui or digital_block.get('capture_ui') or {},
        'upload_pod_workflow': _build_upload_pod_workflow_contract(
            shipment,
            hard_copy_block=hard_copy_block,
            has_hard_copy_step=hard_wizard_step,
            digital_block=digital_block,
        ),
    }


def _build_upload_pod_workflow_contract(
    shipment: Any | None,
    *,
    hard_copy_block: dict[str, Any],
    has_hard_copy_step: bool,
    digital_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Three-call contract for mobile Upload POD wizard."""
    shipment_pk = getattr(shipment, 'pk', '')
    base = f'/api/v1/mobile/driver/jobs/shipments/{shipment_pk}/pod/capture/'
    digital_code = (
        (dict(digital_block or {}).get('execute_action_code') or '').strip()
        or CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE
    )
    hard_copy_code = (
        (hard_copy_block.get('execute_action_code') or '').strip()
        or CANONICAL_FALLBACK_HARD_COPY_POD_ACTION_CODE
    )
    steps: list[dict[str, Any]] = [
        {
            'step': 'digital_evidence',
            'screen_title': DIGITAL_EVIDENCE_SCREEN_TITLE,
            'ui_mode': UI_MODE_DIGITAL_EVIDENCE,
            'get_endpoint': base,
            'post_endpoint': base,
            'execute_action_code': digital_code,
            'primary_button': 'Next',
            'complete_upload_after_execute': not has_hard_copy_step,
        },
    ]
    if has_hard_copy_step and bool(hard_copy_block.get('applicable')):
        steps.append(
            {
                'step': 'hard_copy_confirmation',
                'screen_title': HARD_COPY_SCREEN_TITLE,
                'ui_mode': UI_MODE_HARD_POD_CONFIRMATION,
                'get_endpoint': f'{base}?step=hard_copy_confirmation',
                'documents_endpoint': hard_copy_block.get('documents_endpoint') or '',
                'documents_source': 'shipment_document',
                'submit_endpoint': hard_copy_block.get('submit_endpoint') or '',
                'execute_action_code': hard_copy_code,
                'primary_button': 'Submit POD',
                'complete_upload_after_execute': True,
            },
        )
    return {'steps': steps}


def _empty_hard_copy_block() -> dict[str, Any]:
    return {
        'applicable': False,
        'actionable': False,
        'required': False,
        'submit_allowed': False,
        'pending': False,
        'documents_source': '',
        'action_code': '',
        'documents': [],
        'pages': [],
        'submit_endpoint': '',
        'documents_endpoint': '',
        'execute_action_code': '',
    }


def _empty_pod_section() -> dict[str, Any]:
    return {
        'pod_type': '',
        'pod_doc_count': 0,
        'hard_pod_pending': False,
        'capture_steps': ['digital_evidence'],
        'digital_evidence': {
            'action_code': CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
            'execute_action_code': CANONICAL_FALLBACK_DIGITAL_POD_ACTION_CODE,
            'requirements': {},
        },
        'hard_copy_confirmation': _empty_hard_copy_block(),
    }
