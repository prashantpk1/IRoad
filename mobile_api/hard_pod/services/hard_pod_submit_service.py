"""
mobile_api/hard_pod/services/hard_pod_submit_service.py

Hard POD custody submit orchestration — prepares custody state only.
"""
# HARD POD SUBMIT API — LAYER 3 (Physical Custody) — DRIVER SIDE ONLY
# Responsibility: Record that driver physically has/submits paper document
# Does NOT duplicate digital evidence from POD Capture
# Does NOT write Action Log directly
# Does NOT verify/finalize documents (that is Ops Document Handover)
# Ops Document Handover on desktop is the final verification step
from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping

from django.db import transaction
from django_tenants.utils import schema_context

from mobile_api.hard_pod.guards.hard_pod_replay_guard import HardPodReplayGuard
from mobile_api.hard_pod.guards.hard_pod_security_guard import HardPodSecurityGuard
from mobile_api.hard_pod.services.hard_pod_confirmation_validator import (
    validate_confirmed_pages,
)
from mobile_api.hard_pod.services.hard_pod_custody_service import HardPodCustodyService
from mobile_api.hard_pod.services.hard_pod_idempotency_service import HardPodIdempotencyService
from mobile_api.job_detail.guards.ownership import driver_pk
from mobile_api.pod_capture.models import PODCaptureBundle
from mobile_api.hard_pod.services.hard_pod_custody_promotion import (
    promote_custody_submission,
    resolve_hard_pod_promotion_action_code,
)
from mobile_api.pod_capture.services.pod_capture_action_resolver import (
    resolve_hard_copy_pod_action_code,
)

logger = logging.getLogger('mobile_api.hard_pod')


def _driver_label(driver: Any) -> str:
    for attr in ('driver_no', 'driver_code', 'english_name'):
        val = getattr(driver, attr, None)
        if val:
            return str(val)[:200]
    return str(getattr(driver, 'pk', ''))[:200]


def _coord_str(value: Any) -> str:
    if value is None or value == '':
        return ''
    return str(value).strip()[:32]


class HardPodSubmitService:
    """
    POST custody submission — append-only events, no workflow mutation.

    Execute Action remains authority for Hard POD workflow progression.
    """

    def __init__(
        self,
        *,
        security: HardPodSecurityGuard | None = None,
        replay: HardPodReplayGuard | None = None,
        idempotency: HardPodIdempotencyService | None = None,
        custody: HardPodCustodyService | None = None,
    ) -> None:
        self._security = security or HardPodSecurityGuard()
        self._replay = replay or HardPodReplayGuard()
        self._idempotency = idempotency or HardPodIdempotencyService()
        self._custody = custody or HardPodCustodyService()

    def submit_custody(
        self,
        *,
        driver: Any,
        tenant_schema: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        client_submission_id = (payload.get('client_submission_id') or '').strip()
        shipment_ref = (payload.get('shipment_id') or '').strip()
        driver_id = str(driver_pk(driver) or '').strip()
        media_items = list(payload.get('media') or [])
        confirmed_pages_raw = list(payload.get('confirmed_pages') or [])
        receiver_name = str(payload.get('receiver_name') or '').strip()
        receiver_contact = str(payload.get('receiver_contact') or '').strip()
        handoff_notes = str(payload.get('handoff_notes') or '').strip()
        latitude = _coord_str(payload.get('latitude'))
        longitude = _coord_str(payload.get('longitude'))

        def _sha256_hex(text: str) -> str:
            return hashlib.sha256(text.encode('utf-8')).hexdigest()

        with schema_context(schema):
            shipment = self._security.resolve_and_assert_shipment(
                driver=driver,
                tenant_schema=schema,
                shipment_id=shipment_ref,
            )
            shipment_pk = str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', ''))

            self._security.assert_media_paths(
                media_items,
                tenant_schema=schema,
                driver_pk=driver_id,
                shipment_pk=shipment_pk,
            )
            confirmed_pages = validate_confirmed_pages(
                shipment,
                confirmed_pages_raw,
                tenant_schema=schema,
            )

            file_refs = [
                str(m.get('file_ref') or '').replace('\\', '/').lstrip('/')
                for m in media_items
            ]
            integrity_checksum = _sha256_hex(
                '|'.join(
                    [
                        schema,
                        driver_id,
                        shipment_pk,
                        client_submission_id,
                        receiver_name,
                        receiver_contact,
                        handoff_notes,
                        latitude,
                        longitude,
                        ','.join(sorted(r for r in file_refs if r)),
                        ','.join(
                            sorted(
                                f"{p.get('document_id','')}:{p.get('page_id','')}:{p.get('line_no','')}"
                                for p in confirmed_pages
                            )
                        ),
                    ]
                )
            )

            existing = self._idempotency.get_by_client_submission(
                tenant_schema=schema,
                driver_id=driver_id,
                client_submission_id=client_submission_id,
            )
            if existing is not None:
                self._replay.assert_replay_scope(
                    existing,
                    shipment_id=shipment_pk,
                    driver_id=driver_id,
                    tenant_schema=schema,
                    integrity_checksum=integrity_checksum,
                )
                return self._finalize_submission_response(
                    existing,
                    driver=driver,
                    shipment=shipment,
                    tenant_schema=schema,
                    payload=payload,
                    replayed=True,
                )

            capture_bundle_id = self._resolve_capture_bundle_id(
                tenant_schema=schema,
                shipment_id=shipment_pk,
                driver_id=driver_id,
            )

            with transaction.atomic():
                submission, created = self._idempotency.create_submission(
                    tenant_schema=schema,
                    driver_id=driver_id,
                    shipment_id=shipment_pk,
                    client_submission_id=client_submission_id,
                    receiver_name=receiver_name,
                    receiver_contact=receiver_contact,
                    handoff_notes=handoff_notes,
                    latitude=latitude,
                    longitude=longitude,
                    capture_bundle_id=capture_bundle_id,
                    integrity_checksum=integrity_checksum,
                )

                if not created:
                    self._replay.assert_replay_scope(
                        submission,
                        shipment_id=shipment_pk,
                        driver_id=driver_id,
                        tenant_schema=schema,
                        integrity_checksum=integrity_checksum,
                    )
                    return self._finalize_submission_response(
                        submission,
                        driver=driver,
                        shipment=shipment,
                        tenant_schema=schema,
                        payload=payload,
                        replayed=True,
                    )

                actor_label = _driver_label(driver)
                self._custody.record_collected(
                    submission,
                    actor_id=driver_id,
                    actor_label=actor_label,
                )
                self._custody.record_handoff(
                    submission,
                    actor_id=driver_id,
                    actor_label=actor_label,
                )
                receiver_actor_label = str(
                    payload.get('receiver_name') or ''
                ).strip() or str(payload.get('receiver_contact') or '').strip()
                self._custody.record_received(
                    submission,
                    actor_label=receiver_actor_label,
                )
                self._custody.record_verified(
                    submission,
                    actor_label=receiver_actor_label,
                )
                self._custody.persist_confirmed_pages(submission, confirmed_pages)
                if media_items:
                    self._custody.persist_media_rows(submission, media_items)

            return self._finalize_submission_response(
                submission,
                driver=driver,
                shipment=shipment,
                tenant_schema=schema,
                payload=payload,
                replayed=False,
            )

    def _resolve_capture_bundle_id(
        self,
        *,
        tenant_schema: str,
        shipment_id: str,
        driver_id: str,
    ) -> str | None:
        bundle = (
            PODCaptureBundle.objects.filter(
                tenant_schema=tenant_schema,
                shipment_id=shipment_id,
                driver_id=driver_id,
            )
            .order_by('-created_at')
            .first()
        )
        return str(bundle.id) if bundle else None

    def _finalize_submission_response(
        self,
        submission: Any,
        *,
        driver: Any,
        shipment: Any,
        tenant_schema: str,
        payload: Mapping[str, Any],
        replayed: bool,
    ) -> dict[str, Any]:
        response = self._build_response(
            submission,
            replayed=replayed,
            tenant_schema=tenant_schema,
        )
        execute_step = self._promote_custody_via_execute(
            submission=submission,
            driver=driver,
            shipment=shipment,
            tenant_schema=tenant_schema,
            payload=payload,
        )
        if execute_step:
            response['execute_step'] = execute_step
            if execute_step.get('promoted'):
                submission.refresh_from_db()
                if not (
                    submission.promoted_at
                    and (submission.promotion_action_log_id or '').strip()
                ):
                    execute_step['promoted'] = False
                    execute_step['error_code'] = 'hard_pod_custody_not_promoted'
            if execute_step.get('promoted'):
                cod_code = str(execute_step.get('next_collect_payment_action_code') or '').strip()
                response['next_step'] = {
                    'requires_execute_action': False,
                    'execute_action_code': execute_step.get('execute_action_code') or '',
                    'complete_upload_after_execute': True,
                    'reason': 'hard_pod_workflow_complete',
                    'action_log_id': execute_step.get('action_log_id') or '',
                    'refresh_job_detail': True,
                }
                if cod_code:
                    response['next_step'].update(
                        {
                            'action': 'go_to_payment_collection',
                            'screen': 'collect_payment',
                            'next_action_code': cod_code,
                        },
                    )
            elif execute_step.get('error_code'):
                response['next_step']['execute_error_code'] = execute_step['error_code']
                response['next_step']['custody_submission_id'] = str(
                    getattr(submission, 'pk', '') or ''
                )
                response['next_step']['message'] = str(
                    execute_step.get('message') or ''
                ).strip()
        return response

    def _promote_custody_via_execute(
        self,
        *,
        submission: Any,
        driver: Any,
        shipment: Any,
        tenant_schema: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """
        Promote custody using tenant dynamic Action Master code (kernel path).

        Avoids the mobile execute orchestrator (recursion / stale-sync issues).
        """
        from mobile_api.hard_pod.services.hard_pod_custody_recovery import (
            hard_pod_promotion_guard,
        )

        with hard_pod_promotion_guard():
            return promote_custody_submission(
                submission=submission,
                driver=driver,
                shipment=shipment,
                tenant_schema=tenant_schema,
                payload=payload,
            )

    def _build_response(
        self,
        submission: Any,
        *,
        replayed: bool,
        tenant_schema: str = '',
    ) -> dict[str, Any]:
        custody_payload = self._custody.build_submission_payload(
            submission,
            replayed=replayed,
        )
        timeline = self._custody.timeline_preview(submission)
        return {
            'custody_submission': custody_payload,
            'timeline_preview': timeline,
            'next_step': {
                'requires_execute_action': True,
                'execute_action_code': resolve_hard_pod_promotion_action_code(
                    tenant_schema,
                    shipment=None,
                    fallback=resolve_hard_copy_pod_action_code(tenant_schema),
                ),
                'complete_upload_after_execute': True,
                'reason': 'hard_pod_workflow_progression',
            },
        }
