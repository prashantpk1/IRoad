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


def build_digital_evidence_block(
    shipment: Any | None,
    *,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """
    Layer-1 digital capture contract (GPS / photo / optional video for auto_pod_post).
    """
    schema = (tenant_schema or '').strip()
    action = resolve_default_pod_action(schema) if schema else None
    requirements = build_pod_capture_requirements(
        action,
        pod_capture_type='digital',
        shipment=shipment,
    )
    return {
        'action_code': POD_DIGITAL_ACTION_CODE,
        'execute_action_code': POD_DIGITAL_ACTION_CODE,
        'requirements': {
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
            'note': bool(requirements.get('note')),
            'note_required': bool(requirements.get('note_required')),
            'auto_pod_post': bool(requirements.get('auto_pod_post')),
        },
    }


def build_hard_copy_confirmation_block(
    shipment: Any | None,
    *,
    driver: Any | None = None,
    tenant_schema: str = '',
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
                    tenant_schema=schema,
                )
        return pod_cod_policy.derive_hard_pod_pending(
            shipment,
            tenant_schema=schema,
        )

    hard_pod_pending = _derive_pending()
    has_dn = _shipment_has_delivery_note(shipment, tenant_schema=schema)
    hard_copy_required = (
        hard_pod_pending
        and pod_type == TenantShipment.PodType.HARD.casefold()
        and has_dn
    )
    confirmation_context = (
        build_hard_pod_confirmation_context(
            shipment,
            tenant_schema=schema,
        )
        if hard_copy_required
        else {'documents': [], 'pages': []}
    )
    block: dict[str, Any] = {
        'required': hard_copy_required,
        'pending': hard_pod_pending,
        'action_code': HARD_POD_ACTION_CODE if hard_copy_required else '',
        'documents': list(confirmation_context.get('documents') or []),
        'pages': list(confirmation_context.get('pages') or []),
        'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
        'documents_endpoint': (
            f'/api/v1/mobile/driver/jobs/shipments/{getattr(shipment, "pk", "")}/hard-pod/documents/'
            if hard_copy_required
            else ''
        ),
        'execute_action_code': HARD_POD_ACTION_CODE,
    }
    return block


def build_pod_section_metadata(
    shipment: Any | None,
    *,
    driver: Any | None = None,
    tenant_schema: str = '',
) -> dict[str, Any]:
    """
    Metadata for the Upload POD mobile section only.

    Mobile should render ``hard_copy_confirmation`` only inside the POD flow
    (``GET/POST .../pod/capture/``), not from dashboard or job-level hints.
    """
    if shipment is None:
        return _empty_pod_section()

    hard_copy_block = build_hard_copy_confirmation_block(
        shipment,
        driver=driver,
        tenant_schema=tenant_schema,
    )
    hard_copy_required = bool(hard_copy_block.get('required'))
    steps = ['digital_evidence']
    if hard_copy_required:
        steps.append('hard_copy_confirmation')

    return {
        'pod_type': (getattr(shipment, 'pod_type', None) or '').strip(),
        'pod_doc_count': int(getattr(shipment, 'pod_doc_count', None) or 0),
        'hard_pod_pending': bool(hard_copy_block.get('pending')),
        'capture_steps': steps,
        'digital_evidence': build_digital_evidence_block(
            shipment,
            tenant_schema=tenant_schema,
        ),
        'hard_copy_confirmation': hard_copy_block,
    }


def _empty_hard_copy_block() -> dict[str, Any]:
    return {
        'required': False,
        'pending': False,
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
