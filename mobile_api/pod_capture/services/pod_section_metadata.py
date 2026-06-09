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
from mobile_api.execution.evidence.constants import POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
from mobile_api.hard_pod.services.delivery_note_pages import (
    build_hard_pod_confirmation_context,
)
from mobile_api.pod_capture.policy.pod_capture_policy import (
    build_pod_capture_requirements,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    resolve_default_pod_action,
)
from tenant_workspace.models import TenantShipment


HARD_POD_ACTION_CODE = 'A7H'
POD_DIGITAL_ACTION_CODE = 'A7'
HARD_COPY_SCREEN_TITLE = 'Hard POD Collection Confirmation'
DIGITAL_EVIDENCE_SCREEN_TITLE = 'Capturing Action Evidences'
UI_MODE_HARD_POD_CONFIRMATION = 'hard_pod_collection_confirmation'
UI_MODE_DIGITAL_EVIDENCE = 'digital_evidence'


def _shipment_has_delivery_note(shipment: Any | None, *, tenant_schema: str) -> bool:
    """Hard-copy confirmation requires a portal DN (Is Delivery Note? = Yes)."""
    schema = (tenant_schema or '').strip()
    if shipment is None or not schema:
        return False
    try:
        with schema_context(schema):
            from tenant_workspace.models import TenantShipmentDocument

            return TenantShipmentDocument.objects.filter(
                shipment_id=getattr(shipment, 'pk', None),
                is_delivery_note=True,
            ).exists()
    except Exception:
        return False


def build_hard_copy_confirmation_ui(
    pages: list[dict[str, Any]],
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
        },
    }


def build_digital_capture_ui(
    requirements: dict[str, Any],
    *,
    has_hard_copy_step: bool = False,
) -> dict[str, Any]:
    """Mobile layout contract for Layer-1 digital evidence (Capturing Action Evidences)."""
    video_max_seconds = int(
        requirements.get('video_max_duration_seconds')
        or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
    )
    photo_required = bool(requirements.get('photo')) or int(
        requirements.get('photo_min_count') or 0
    ) > 0
    video_required = bool(requirements.get('video')) or int(
        requirements.get('video_min_count') or 0
    ) > 0
    return {
        'ui_mode': UI_MODE_DIGITAL_EVIDENCE,
        'screen_title': DIGITAL_EVIDENCE_SCREEN_TITLE,
        'gps_banner': {
            'label': 'GPS captured + Evidence Media',
            'subtitle': f'Video clips must be max {video_max_seconds} seconds.',
        },
        'sections': [
            {
                'id': 'evidence_photos',
                'label': 'Add Evidence Photos',
                'media_type': 'photo',
                'required': photo_required,
                'min_count': max(int(requirements.get('photo_min_count') or 0), 1 if photo_required else 0),
                'capture_label': 'Capture Photos',
            },
            {
                'id': 'evidence_video',
                'label': 'Add Evidence Video',
                'media_type': 'video',
                'required': video_required and not bool(requirements.get('video_optional')),
                'min_count': int(requirements.get('video_min_count') or 0),
                'max_count': max(int(requirements.get('video_max_count') or 0), 1),
                'max_duration_seconds': video_max_seconds,
                'capture_label': f'Record Video Clip (max {video_max_seconds}s)',
            },
            {
                'id': 'note',
                'label': 'Note',
                'media_type': 'note',
                'required': bool(requirements.get('note_required')),
                'placeholder': 'Write a note...',
            },
        ],
        'footer_hint': 'Upload every mandatory signed document page.',
        'primary_button': _build_digital_primary_button(has_hard_copy_step),
    }


def _build_digital_primary_button(has_hard_copy_step: bool) -> dict[str, Any]:
    """
    Digital screen ends with Next — not Submit POD.

    Hard POD: Next → execute A7 → open hard-copy confirmation wizard step.
    Soft / no DN: Next → execute A7 → Upload POD complete.
    """
    button: dict[str, Any] = {
        'label': 'Next',
        'action': 'submit_digital_evidence',
        'execute_action_code': POD_DIGITAL_ACTION_CODE,
    }
    if has_hard_copy_step:
        button['wizard_next_step'] = 'hard_copy_confirmation'
        button['complete_upload_after_execute'] = False
    else:
        button['complete_upload_after_execute'] = True
    return button


def _build_digital_media_steps(requirements: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered capture slots for mobile Upload POD (digital evidence layer)."""
    steps: list[dict[str, Any]] = []
    if bool(requirements.get('photo')) or int(requirements.get('photo_min_count') or 0) > 0:
        steps.append(
            {
                'media_type': 'photo',
                'required': True,
                'min_count': max(int(requirements.get('photo_min_count') or 0), 1),
                'max_count': max(int(requirements.get('photo_min_count') or 0), 1),
                'label': 'Delivery note photo',
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
    video_required = bool(requirements.get('video')) or int(
        requirements.get('video_min_count') or 0
    ) > 0
    video_optional = bool(requirements.get('video_optional')) and not video_required
    if (
        video_required
        or video_optional
        or int(requirements.get('video_max_count') or 0) > 0
    ):
        steps.append(
            {
                'media_type': 'video',
                'required': video_required,
                'optional': video_optional,
                'min_count': int(requirements.get('video_min_count') or 0),
                'max_count': max(int(requirements.get('video_max_count') or 0), 1),
                'max_duration_seconds': int(
                    requirements.get('video_max_duration_seconds')
                    or POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
                ),
                'label': 'Delivery video',
            }
        )
    return steps


def build_digital_evidence_block(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    has_hard_copy_step: bool = False,
) -> dict[str, Any]:
    """
    Layer-1 digital capture contract (GPS / photo / signature / video for auto_pod_post).
    """
    schema = (tenant_schema or '').strip()
    action = resolve_default_pod_action(schema) if schema else None
    requirements = build_pod_capture_requirements(
        action,
        pod_capture_type='digital',
        shipment=shipment,
    )
    requirement_payload = {
        'gps': bool(requirements.get('gps')),
        'photo': bool(requirements.get('photo')),
        'photo_min_count': int(requirements.get('photo_min_count') or 0),
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
    }
    return {
        'action_code': POD_DIGITAL_ACTION_CODE,
        'execute_action_code': POD_DIGITAL_ACTION_CODE,
        'requirements': requirement_payload,
        'media_steps': _build_digital_media_steps(requirement_payload),
        'capture_mode': 'digital_evidence',
        'screen_title': 'Capturing Action Evidences',
        'capture_ui': build_digital_capture_ui(
            requirement_payload,
            has_hard_copy_step=has_hard_copy_step,
        ),
    }


def _hard_copy_confirmation_actionable(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
) -> bool:
    """
    Hard-copy checklist belongs after digital A7 (or custody submit), not inside Upload POD early.
    """
    evidence = log_evidence or {}
    if evidence.get('pod_uploaded'):
        return True
    try:
        from iroad_tenants.operation_execution import _pending_hard_pod_custody_exists

        if _pending_hard_pod_custody_exists(shipment):
            return True
    except Exception:
        pass
    _ = tenant_schema
    return False


def _shipment_hard_copy_applicable(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
    log_evidence: dict[str, bool] | None = None,
    dn_pages: list[dict[str, Any]] | None = None,
) -> bool:
    """Upload POD wizard includes hard-copy step (Hard POD + shipment DN pages)."""
    if shipment is None:
        return False
    pod_type = (getattr(shipment, 'pod_type', None) or '').strip().casefold()
    if pod_type != TenantShipment.PodType.HARD.casefold():
        return False
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    if status in {
        TenantShipment.ShipmentStatus.CLOSED,
        TenantShipment.ShipmentStatus.CANCELLED,
    }:
        return False
    pages = list(dn_pages or [])
    if pages:
        return True
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
    shipment_pk = getattr(shipment, 'pk', '')
    block: dict[str, Any] = {
        'applicable': applicable,
        'actionable': actionable,
        'required': applicable,
        'submit_allowed': actionable and hard_pod_pending,
        'pending': hard_pod_pending if applicable else False,
        'documents_source': 'shipment_document' if applicable else '',
        'action_code': HARD_POD_ACTION_CODE if applicable else '',
        'documents': list(confirmation_context.get('documents') or []),
        'pages': pages,
        'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
        'documents_endpoint': (
            f'/api/v1/mobile/driver/jobs/shipments/{shipment_pk}/hard-pod/documents/'
            if applicable
            else ''
        ),
        'execute_action_code': HARD_POD_ACTION_CODE,
        'ui_mode': UI_MODE_HARD_POD_CONFIRMATION if applicable else '',
        'screen_title': HARD_COPY_SCREEN_TITLE if applicable else '',
    }
    if applicable and pages:
        block['confirmation_ui'] = build_hard_copy_confirmation_ui(pages)
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
    steps = ['digital_evidence']
    if hard_copy_applicable:
        steps.append('hard_copy_confirmation')

    digital_block = build_digital_evidence_block(
        shipment,
        tenant_schema=tenant_schema,
        has_hard_copy_step=hard_copy_applicable,
    )
    digital_complete = bool(evidence.get('pod_uploaded'))
    return {
        'pod_type': (getattr(shipment, 'pod_type', None) or '').strip(),
        'pod_doc_count': int(getattr(shipment, 'pod_doc_count', None) or 0),
        'hard_pod_pending': bool(hard_copy_block.get('pending')),
        'digital_evidence_complete': digital_complete,
        'capture_steps': steps,
        'digital_evidence': digital_block,
        'hard_copy_confirmation': hard_copy_block,
        'screen_title': digital_block.get('screen_title') or DIGITAL_EVIDENCE_SCREEN_TITLE,
        'capture_ui': digital_block.get('capture_ui') or {},
        'upload_pod_workflow': _build_upload_pod_workflow_contract(
            shipment,
            hard_copy_block=hard_copy_block,
            has_hard_copy_step=hard_copy_applicable,
        ),
    }


def _build_upload_pod_workflow_contract(
    shipment: Any | None,
    *,
    hard_copy_block: dict[str, Any],
    has_hard_copy_step: bool,
) -> dict[str, Any]:
    """Three-call contract for mobile Upload POD wizard."""
    shipment_pk = getattr(shipment, 'pk', '')
    base = f'/api/v1/mobile/driver/jobs/shipments/{shipment_pk}/pod/capture/'
    steps: list[dict[str, Any]] = [
        {
            'step': 'digital_evidence',
            'screen_title': DIGITAL_EVIDENCE_SCREEN_TITLE,
            'ui_mode': UI_MODE_DIGITAL_EVIDENCE,
            'get_endpoint': base,
            'post_endpoint': base,
            'execute_action_code': POD_DIGITAL_ACTION_CODE,
            'primary_button': 'Next',
            'complete_upload_after_execute': not has_hard_copy_step,
        },
    ]
    if has_hard_copy_step:
        steps.append(
            {
                'step': 'hard_copy_confirmation',
                'screen_title': HARD_COPY_SCREEN_TITLE,
                'ui_mode': UI_MODE_HARD_POD_CONFIRMATION,
                'get_endpoint': f'{base}?step=hard_copy_confirmation',
                'documents_endpoint': hard_copy_block.get('documents_endpoint') or '',
                'documents_source': 'shipment_document',
                'submit_endpoint': hard_copy_block.get('submit_endpoint') or '',
                'execute_action_code': HARD_POD_ACTION_CODE,
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
            'action_code': POD_DIGITAL_ACTION_CODE,
            'execute_action_code': POD_DIGITAL_ACTION_CODE,
            'requirements': {},
        },
        'hard_copy_confirmation': _empty_hard_copy_block(),
    }
