"""
mobile_api/pod_capture/dto/pod_capture_response_builder.py

Final POD Capture API response envelope.
"""
from __future__ import annotations

from typing import Any

from mobile_api.execution.evidence.constants import POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS
from mobile_api.pod_capture.dto.pod_capture_context import PodCaptureContext
from mobile_api.pod_capture.dto.staging_models import PODCaptureBundle, PODCaptureMedia
from mobile_api.pod_capture.services.pod_section_metadata import build_pod_section_metadata


class PodCaptureResponseBuilder:
    """Build mobile API ``data`` for POST pod/capture/."""

    def build(self, context: PodCaptureContext) -> dict[str, Any]:
        bundle = context.bundle
        if bundle is None:
            shipment = getattr(context, 'shipment', None)
            return {
                'capture_bundle': {},
                'compliance': {},
                'sync_metadata': dict(context.sync_metadata or {}),
                'next_step': {'requires_execute_action': False},
                'pod_section': build_pod_section_metadata(
                    shipment,
                    driver=getattr(context, 'driver', None),
                    tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
                ),
            }

        staged_media = [self._build_media_row(row) for row in context.staged_media]
        capture_bundle = self._build_capture_bundle(bundle, context, staged_media)
        compliance = self._build_compliance(context, staged_media)
        shipment = getattr(context, 'shipment', None)
        pod_section = build_pod_section_metadata(
            shipment,
            driver=getattr(context, 'driver', None),
            tenant_schema=(getattr(context, 'tenant_schema', None) or ''),
        )
        next_step = self._build_next_step(bundle, context, pod_section=pod_section)

        return {
            'capture_bundle': capture_bundle,
            'compliance': compliance,
            'sync_metadata': dict(context.sync_metadata or {}),
            'next_step': next_step,
            'pod_section': pod_section,
        }

    def _build_capture_bundle(
        self,
        bundle: PODCaptureBundle,
        context: PodCaptureContext,
        staged_media: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            'capture_bundle_id': bundle.bundle_id,
            'bundle_id': bundle.bundle_id,
            'client_capture_id': bundle.client_capture_id,
            'shipment_id': bundle.shipment_id,
            'driver_id': bundle.driver_id,
            'tenant_schema': bundle.tenant_schema,
            'status': bundle.status.value,
            'content_hash': bundle.content_hash,
            'media_count': bundle.media_count,
            'pod_type': (context.pod_capture_type or '').strip() or None,
            'notes': (context.notes or '').strip() or None,
            'expires_at': _iso(bundle.expires_at),
            'promoted_at': _iso(bundle.promoted_at),
            'replayed': bool(context.idempotent_replay),
            'staged_media': staged_media,
            'execute_ready': bundle.is_promotable(),
            'promotion': {
                'ready_for_execute': bundle.is_promotable(),
                'promoted': bundle.is_promoted(),
                'action_log_id': bundle.promotion_action_log_id,
            },
        }

    def _build_compliance(
        self,
        context: PodCaptureContext,
        staged_media: list[dict[str, Any]],
    ) -> dict[str, Any]:
        requirements = dict(context.compliance_requirements or {})
        photo_count = sum(
            1
            for row in staged_media
            if (row.get('media_type') or '').casefold() in {'photo', 'signature'}
        )
        video_count = sum(
            1 for row in staged_media if (row.get('media_type') or '').casefold() == 'video'
        )
        signature_count = sum(
            1
            for row in staged_media
            if (row.get('media_type') or '').casefold() == 'signature'
        )
        document_count = sum(
            1 for row in staged_media if (row.get('media_type') or '').casefold() == 'document'
        )

        gps_required = bool(requirements.get('gps'))
        gps_provided = bool(
            (context.latitude or '').strip() and (context.longitude or '').strip()
        )

        return {
            'validated': bool(requirements) or bool(context.idempotent_replay),
            'replayed': bool(context.idempotent_replay),
            'pod_type': (context.pod_capture_type or '').strip() or None,
            'target_action_code': (context.target_action_code or '').strip() or None,
            'requirements': {
                'gps': gps_required,
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
                'document_min_count': int(requirements.get('document_min_count') or 0),
            },
            'summary': {
                'gps_required': gps_required,
                'gps_provided': gps_provided,
                'gps_satisfied': (not gps_required) or gps_provided,
                'photo_count': photo_count,
                'video_count': video_count,
                'signature_count': signature_count,
                'document_count': document_count,
                'notes_provided': bool((context.notes or '').strip()),
                'media_count': len(staged_media),
            },
        }

    def _build_next_step(
        self,
        bundle: PODCaptureBundle,
        context: PodCaptureContext,
        *,
        pod_section: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requires_execute = bundle.is_promotable() and not bundle.is_promoted()
        hard_block = dict((pod_section or {}).get('hard_copy_confirmation') or {})
        digital_block = dict((pod_section or {}).get('digital_evidence') or {})
        has_hard_copy_step = bool(hard_block.get('applicable') or hard_block.get('required'))
        shipment_pk = getattr(context, 'shipment_id', '') or ''
        base_capture = f'/api/v1/mobile/driver/jobs/shipments/{shipment_pk}/pod/capture/'
        digital_code = (
            (context.target_action_code or '').strip()
            or (digital_block.get('execute_action_code') or '').strip()
            or (digital_block.get('action_code') or '').strip()
        )
        hard_copy_code = (hard_block.get('execute_action_code') or '').strip()

        step: dict[str, Any] = {
            'requires_execute_action': requires_execute,
            'bundle_id': bundle.bundle_id,
            'capture_bundle_id': bundle.bundle_id,
            'execute_payload_hint': {
                'capture_bundle_id': bundle.bundle_id,
                'latitude': 'from device GPS',
                'longitude': 'from device GPS',
            },
            'target_action_code': digital_code,
            'execute_action_code': digital_code,
            'execute_ready': bundle.is_promotable(),
        }
        if has_hard_copy_step:
            step.update(
                {
                    'wizard_next_step': 'hard_copy_confirmation',
                    'wizard_next_get_endpoint': f'{base_capture}?step=hard_copy_confirmation',
                    'documents_endpoint': hard_block.get('documents_endpoint') or '',
                    'custody_submit_endpoint': hard_block.get('submit_endpoint') or '',
                    'after_custody_execute_action_code': hard_copy_code,
                    'complete_upload_after_execute': False,
                },
            )
        else:
            step['complete_upload_after_execute'] = True
        return step

    @staticmethod
    def _build_media_row(row: PODCaptureMedia) -> dict[str, Any]:
        return {
            'media_id': row.media_id,
            'shipment_id': row.shipment_id,
            'driver_id': row.driver_id,
            'tenant_schema': row.tenant_schema,
            'client_capture_id': row.client_capture_id,
            'media_type': row.media_type,
            'file_ref': row.file_ref,
            'promoted': bool(row.promoted),
            'mime_type': row.mime_type,
            'checksum': row.checksum,
            'line_no': row.line_no,
            'file_name': row.file_name,
            'description': row.description,
            'captured_at': _iso(row.captured_at),
            'uploaded_at': _iso(row.uploaded_at),
        }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)
