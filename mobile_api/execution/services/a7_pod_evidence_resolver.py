"""
mobile_api/execution/services/a7_pod_evidence_resolver.py

Consolidate fragmented POD uploads before A7 Execute validation.

Mobile often uploads photos and video in separate ``POST .../pod/capture/`` calls
(or only sends files on Execute). Each call can create its own READY bundle.
Execute A7 must merge those rows (and any inline execute media) before the
``video_required`` check and before bundle promotion.
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.evidence.action_log_media_persistence import normalize_media_items
from mobile_api.execution.evidence.evidence_validation_service import (
    EvidenceValidationService,
    extract_capture_bundle_id,
)
from mobile_api.execution.evidence.constants import VIDEO_MEDIA_TYPES
from mobile_api.pod_capture.repositories.durable_bundle_repository import normalize_file_ref
from mobile_api.utils.file_upload_handler import infer_media_type

logger = logging.getLogger('mobile_api.execution.a7_pod')


def prepare_a7_execute_evidence(
    context: ExecuteActionContext,
    *,
    request: Any | None = None,
) -> None:
    """
    Merge staged POD media and/or stage execute inline media before A7 validation.

    Safe to call for every execute — no-op unless action is shipment A7.
    """
    if context.idempotent_replay:
        return
    if not _is_pod_shipment_execute(context):
        return

    payload = dict(context.payload or {})
    inline_rows = _inline_media_dicts(payload)
    bundle_rows, bundle_candidates = _collect_ready_bundle_media(context)
    merged_rows = _merge_media_dicts(inline_rows, bundle_rows)

    context.resolver_meta = dict(context.resolver_meta or {})
    if merged_rows:
        from mobile_api.execution.evidence.pod_evidence_consolidation import (
            consolidate_pod_evidence_dicts,
        )
        from mobile_api.pod_capture.policy.pod_capture_policy import (
            build_pod_capture_requirements,
        )

        pod_requirements = build_pod_capture_requirements(
            context.operation_action,
            pod_capture_type=str((payload or {}).get('pod_type') or 'digital'),
            shipment=context.shipment,
        )
        merged_rows = consolidate_pod_evidence_dicts(merged_rows, pod_requirements)
        context.resolver_meta['pod_capture_merged_bundle_media'] = merged_rows

    explicit_bundle_id = extract_capture_bundle_id(payload)
    # Prefer the bundle that actually contains video when uploads were split
    # across multiple ``pod/capture`` calls — explicit id may be photo-only.
    if bundle_candidates and merged_rows:
        primary_bundle_id = _pick_primary_bundle_id(
            bundle_candidates,
            merged_rows,
        )
    else:
        primary_bundle_id = explicit_bundle_id

    if not primary_bundle_id and merged_rows and _can_stage_from_execute(context, merged_rows):
        primary_bundle_id = _stage_consolidated_capture(context, merged_rows, request=request)

    if primary_bundle_id:
        payload['capture_bundle_id'] = primary_bundle_id
        context.payload = payload
        logger.info(
            'a7_pod_evidence_resolver shipment=%s bundle=%s merged_media=%s',
            EvidenceValidationService._shipment_key(context),
            primary_bundle_id,
            len(merged_rows),
        )


def promote_merged_a7_media(
    context: ExecuteActionContext,
    *,
    primary_bundle_id: str,
    action_log: Any,
) -> None:
    """
    After primary bundle promotion, append media from sibling staged bundles.

    Idempotent when resolver did not merge extra rows.
    """
    if context.idempotent_replay or action_log is None:
        return
    merged = list((context.resolver_meta or {}).get('pod_capture_merged_bundle_media') or [])
    if not merged:
        return

    from mobile_api.pod_capture.staging.evidence_promotion_service import (
        EvidencePromotionService,
        staged_media_to_action_log_items,
    )
    from mobile_api.pod_capture.policy.pod_evidence_immutability_policy import (
        persist_pod_action_log_media,
    )
    from mobile_api.pod_capture.dto.staging_models import PODCaptureMedia

    staging = EvidencePromotionService()._staging  # noqa: SLF001
    primary_refs = {
        normalize_file_ref(str(getattr(row, 'file_ref', '') or ''))
        for row in staging.get_media(primary_bundle_id)
    }
    extra_items = []
    for row in merged:
        ref = normalize_file_ref(str(row.get('file_ref') or ''))
        if not ref or ref in primary_refs:
            continue
        extra_items.append(
            PODCaptureMedia(
                media_id=str(row.get('media_id') or ''),
                bundle_id=primary_bundle_id,
                shipment_id=str(row.get('shipment_id') or ''),
                driver_id=str(row.get('driver_id') or ''),
                tenant_schema=str(row.get('tenant_schema') or ''),
                client_capture_id=str(row.get('client_capture_id') or ''),
                media_type=str(row.get('media_type') or ''),
                file_ref=str(row.get('file_ref') or ''),
                mime_type=str(row.get('mime_type') or ''),
                line_no=int(row.get('line_no') or 0),
                file_name=str(row.get('file_name') or ''),
            )
        )
    if not extra_items:
        return
    persist_pod_action_log_media(
        action_log,
        staged_media_to_action_log_items(extra_items),
    )


def _is_pod_shipment_execute(context: ExecuteActionContext) -> bool:
    """True when execute targets tenant Upload POD (``auto_pod_post`` / dynamic OA-* code)."""
    if (context.job_type or '').strip().casefold() != 'shipment':
        return False
    operation_action = context.operation_action
    if operation_action is not None:
        if bool(getattr(operation_action, 'auto_pod_post', False)):
            return True
        from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
            is_pod_upload_action,
        )

        return is_pod_upload_action(operation_action)
    from types import SimpleNamespace

    from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
        is_pod_upload_action,
    )

    code = (context.action_code or '').strip()
    if not code:
        return False
    return is_pod_upload_action(SimpleNamespace(action_code=code, english_label=''))


# Backward-compatible alias for tests and legacy imports.
_is_a7_shipment_execute = _is_pod_shipment_execute


def _inline_media_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in normalize_media_items(list(payload.get('media') or [])):
        file_ref = (item.file_ref or '').strip()
        if not file_ref and not item.upload and not (item.media_id or '').strip():
            continue
        rows.append(
            {
                'media_type': item.media_type,
                'file_ref': file_ref,
                'file_name': item.file_name,
                'line_no': item.line_no,
                'mime_type': '',
            }
        )
    return rows


def _shipment_keys(context: ExecuteActionContext) -> list[str]:
    keys: list[str] = []
    for candidate in (
        EvidenceValidationService._shipment_key(context),
        str(context.job_id or '').strip(),
        str(getattr(context.shipment, 'pk', '') or '').strip(),
        str(getattr(context.shipment, 'shipment_id', '') or '').strip(),
        str(getattr(context.shipment, 'shipment_no', '') or '').strip(),
    ):
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


def _collect_ready_bundle_media(
    context: ExecuteActionContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from mobile_api.pod_capture.models import PODCaptureBundle
    from mobile_api.pod_capture.staging.evidence_staging_service import EvidenceStagingService

    tenant = (context.tenant_schema or '').strip()
    driver_pk = EvidenceValidationService._driver_pk(context.driver)
    if not (tenant and driver_pk):
        return [], []

    staging = EvidenceStagingService()
    seen_bundle_ids: set[str] = set()
    bundle_candidates: list[dict[str, Any]] = []
    merged_rows: list[dict[str, Any]] = []

    for shipment_id in _shipment_keys(context):
        bundles = (
            PODCaptureBundle.objects.filter(
                tenant_schema=tenant,
                shipment_id=shipment_id,
                driver_id=driver_pk,
                bundle_status=PODCaptureBundle.BundleStatus.READY,
                expires_at__gt=timezone.now(),
            )
            .order_by('-created_at')[:8]
        )
        for bundle in bundles:
            bundle_id = str(
                getattr(bundle, 'pk', None)
                or getattr(bundle, 'id', None)
                or getattr(bundle, 'bundle_id', None)
                or ''
            ).strip()
            if not bundle_id or bundle_id in seen_bundle_ids:
                continue
            seen_bundle_ids.add(bundle_id)
            media_rows = staging.get_media(bundle_id)
            media_dicts = [_media_row_to_dict(row) for row in media_rows]
            bundle_candidates.append(
                {
                    'bundle_id': bundle_id,
                    'media': media_dicts,
                    'score': _score_media_dicts(media_dicts),
                    'created_at': bundle.created_at,
                }
            )
            merged_rows = _merge_media_dicts(merged_rows, media_dicts)

    return merged_rows, bundle_candidates


def _media_row_to_dict(row: Any) -> dict[str, Any]:
    file_ref = str(getattr(row, 'file_ref', '') or '').strip()
    file_name = str(getattr(row, 'file_name', '') or '').strip()
    media_type = infer_media_type(
        explicit=str(getattr(row, 'media_type', '') or ''),
        content_type=str(getattr(row, 'mime_type', '') or ''),
        file_ref=file_ref,
        file_name=file_name,
        duration_seconds=getattr(row, 'duration_seconds', None),
    )
    return {
        'media_id': str(getattr(row, 'media_id', '') or ''),
        'media_type': media_type,
        'file_ref': file_ref,
        'file_name': file_name,
        'mime_type': str(getattr(row, 'mime_type', '') or ''),
        'line_no': int(getattr(row, 'line_no', None) or 0),
        'tenant_schema': str(getattr(row, 'tenant_schema', '') or ''),
        'driver_id': str(getattr(row, 'driver_id', '') or ''),
        'shipment_id': str(getattr(row, 'shipment_id', '') or ''),
        'client_capture_id': str(getattr(row, 'client_capture_id', '') or ''),
    }


def _merge_media_dicts(
    *groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for group in groups:
        for row in group:
            if not isinstance(row, dict):
                continue
            file_ref = normalize_file_ref(str(row.get('file_ref') or ''))
            if not file_ref or file_ref in seen_refs:
                continue
            seen_refs.add(file_ref)
            normalized = dict(row)
            normalized['media_type'] = infer_media_type(
                explicit=str(row.get('media_type') or ''),
                content_type=str(row.get('mime_type') or ''),
                file_ref=file_ref,
                file_name=str(row.get('file_name') or ''),
                duration_seconds=row.get('duration_seconds'),
            )
            normalized['file_ref'] = file_ref
            if row.get('duration_seconds') is not None:
                normalized['duration_seconds'] = row.get('duration_seconds')
            merged.append(normalized)
    merged.sort(key=lambda row: int(row.get('line_no') or 0))
    return merged


def _score_media_dicts(rows: list[dict[str, Any]]) -> int:
    video_count = 0
    photo_count = 0
    for row in rows:
        media_type = infer_media_type(
            explicit=str(row.get('media_type') or ''),
            content_type=str(row.get('mime_type') or ''),
            file_ref=str(row.get('file_ref') or ''),
            file_name=str(row.get('file_name') or ''),
            duration_seconds=row.get('duration_seconds'),
        )
        if media_type in VIDEO_MEDIA_TYPES:
            video_count += 1
        elif media_type in {'photo', 'signature'}:
            photo_count += 1
    return video_count * 100 + photo_count


def _pick_primary_bundle_id(
    candidates: list[dict[str, Any]],
    merged_rows: list[dict[str, Any]],
) -> str:
    if not candidates:
        return ''
    if not merged_rows:
        return str(candidates[0].get('bundle_id') or '')

    has_video = any(
        infer_media_type(
            explicit=str(row.get('media_type') or ''),
            content_type=str(row.get('mime_type') or ''),
            file_ref=str(row.get('file_ref') or ''),
            file_name=str(row.get('file_name') or ''),
            duration_seconds=row.get('duration_seconds'),
        )
        in VIDEO_MEDIA_TYPES
        for row in merged_rows
    )

    ranked = sorted(
        candidates,
        key=lambda item: (
            int(item.get('score') or 0),
            item.get('created_at') or timezone.now(),
        ),
        reverse=True,
    )
    if has_video:
        for item in ranked:
            media = list(item.get('media') or [])
            if any(
                infer_media_type(
                    explicit=str(row.get('media_type') or ''),
                    content_type=str(row.get('mime_type') or ''),
                    file_ref=str(row.get('file_ref') or ''),
                    file_name=str(row.get('file_name') or ''),
                    duration_seconds=row.get('duration_seconds'),
                )
                in VIDEO_MEDIA_TYPES
                for row in media
            ):
                return str(item.get('bundle_id') or '')
    return str(ranked[0].get('bundle_id') or '')


def _can_stage_from_execute(
    context: ExecuteActionContext,
    merged_rows: list[dict[str, Any]],
) -> bool:
    if not merged_rows:
        return False
    payload = context.payload or {}
    if not (payload.get('client_action_id') and payload.get('content_hash')):
        return False
    return any((row.get('file_ref') or '').strip() for row in merged_rows)


def _stage_consolidated_capture(
    context: ExecuteActionContext,
    merged_rows: list[dict[str, Any]],
    *,
    request: Any | None = None,
) -> str:
    from mobile_api.pod_capture.exceptions import PodCaptureError
    from mobile_api.pod_capture.services.pod_capture_orchestrator import PodCaptureOrchestrator

    payload = dict(context.payload or {})
    client_action_id = str(payload.get('client_action_id') or '').strip()
    capture_payload = {
        'client_capture_id': f'a7-exec-{client_action_id}',
        'content_hash': str(payload.get('content_hash') or '').strip(),
        'workflow_version': str(payload.get('workflow_version') or '').strip(),
        'target_action_code': 'A7',
        'pod_capture_type': 'digital',
        'latitude': payload.get('latitude'),
        'longitude': payload.get('longitude'),
        'notes': str(payload.get('notes') or '').strip(),
        'media': [
            {
                'media_type': row.get('media_type'),
                'file_ref': row.get('file_ref'),
                'file_name': row.get('file_name'),
                'sort_order': row.get('line_no') or index + 1,
                'duration_seconds': row.get('duration_seconds'),
            }
            for index, row in enumerate(merged_rows)
            if (row.get('file_ref') or '').strip()
        ],
    }
    if not capture_payload['media']:
        return ''

    try:
        data = PodCaptureOrchestrator().capture_pod_evidence(
            driver=context.driver,
            tenant_schema=(context.tenant_schema or '').strip(),
            shipment_id=str(context.job_id or '').strip(),
            payload=capture_payload,
            request=request,
            user_id=str(context.user_id or ''),
            job_type='shipment',
        )
    except PodCaptureError as exc:
        logger.warning(
            'a7_pod_evidence_stage_failed shipment=%s code=%s',
            context.job_id,
            exc.code,
        )
        return ''

    bundle = dict(data.get('capture_bundle') or {})
    return str(bundle.get('capture_bundle_id') or bundle.get('bundle_id') or '').strip()
