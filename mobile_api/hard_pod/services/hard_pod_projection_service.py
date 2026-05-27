"""
mobile_api/hard_pod/services/hard_pod_projection_service.py

Build shipment-centric Hard POD projections from tenant + public-schema sources.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from tenant_workspace.models import TenantOperationActionLog, TenantShipmentDocument

from mobile_api.dashboard.selectors import pod_cod_policy
from mobile_api.hard_pod.projections.hard_pod_projection_builder import (
    VERIFICATION_PENDING,
    VERIFICATION_VERIFIED,
    build_handoff_block,
    build_portal_snapshot,
    build_receiver_block,
    build_receiver_block_from_submission,
    build_shipment_row,
    build_timeline_preview,
    derive_custody_state,
)
from mobile_api.hard_pod.services.hard_pod_reconciliation_service import (
    reconcile_hard_pod_row,
    workflow_blocked_read_only,
)
from mobile_api.job_detail.guards.ownership import driver_owns_shipment_leg
from mobile_api.pod_capture.models import PODCaptureBundle
from mobile_api.hard_pod.models import (
    HardPODCustodySubmission,
    HardPODCustodySubmissionEvent,
)
from mobile_api.pod_capture.policy.compliance_log_evidence import log_evidence_flags


def _driver_pk(driver: Any) -> str:
    pk = getattr(driver, 'pk', None) or getattr(driver, 'driver_id', None)
    return str(pk or '').strip()


def _shipment_pk(shipment: Any) -> str:
    return str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', '')).strip()


def _load_action_logs_by_shipment(shipment_ids: list[str]) -> dict[str, list[Any]]:
    if not shipment_ids:
        return {}
    logs = (
        TenantOperationActionLog.objects.filter(shipment_id__in=shipment_ids)
        .select_related('operation_action')
        .order_by('shipment_id', '-log_date', '-created_at')
    )
    grouped: dict[str, list[Any]] = defaultdict(list)
    for log in logs:
        sid = str(getattr(log, 'shipment_id', '') or '')
        if len(grouped[sid]) < 50:
            grouped[sid].append(log)
    return grouped


def _load_custody_by_shipment(
    tenant_schema: str,
    shipment_ids: list[str],
    *,
    driver_id: str,
) -> dict[str, dict[str, Any]]:
    if not shipment_ids:
        return {}

    bundles = list(
        PODCaptureBundle.objects.filter(
            tenant_schema=tenant_schema,
            shipment_id__in=shipment_ids,
            driver_id=driver_id,
        ).order_by('shipment_id', '-created_at')
    )

    submissions = list(
        HardPODCustodySubmission.objects.filter(
            tenant_schema=tenant_schema,
            shipment_id__in=shipment_ids,
            driver_id=driver_id,
        ).order_by('shipment_id', '-submitted_at', '-created_at')
    )
    submission_events = list(
        HardPODCustodySubmissionEvent.objects.filter(
            tenant_schema=tenant_schema,
            shipment_id__in=shipment_ids,
            driver_id=driver_id,
        ).order_by('shipment_id', 'occurred_at', 'created_at')
    )

    by_shipment: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            'events': [],
            'receipt': None,
            'verification': None,
            'bundle_id': None,
            'submission': None,
        }
    )

    for bundle in bundles:
        bucket = by_shipment[bundle.shipment_id]
        if bucket['bundle_id'] is None:
            bucket['bundle_id'] = str(bundle.id)

    for sub in submissions:
        bucket = by_shipment[sub.shipment_id]
        if bucket['submission'] is None:
            bucket['submission'] = sub
            if sub.capture_bundle_id:
                bucket['bundle_id'] = str(sub.capture_bundle_id)

    submission_events_by_shipment: dict[str, list[Any]] = defaultdict(list)
    for ev in submission_events:
        submission_events_by_shipment[ev.shipment_id].append(ev)

    for sid, bucket in by_shipment.items():
        if submission_events_by_shipment.get(sid):
            bucket['events'] = submission_events_by_shipment[sid]

    return by_shipment


def _load_portal_pod_documents(shipment_ids: list[str]) -> dict[str, Any]:
    if not shipment_ids:
        return {}
    docs = (
        TenantShipmentDocument.objects.filter(
            shipment_id__in=shipment_ids,
            document_type__iexact='pod',
        )
        .order_by('shipment_id', '-updated_at')
    )
    result: dict[str, Any] = {}
    for doc in docs:
        sid = str(getattr(doc, 'shipment_id', '') or '')
        if sid not in result:
            result[sid] = doc
    return result


def is_pending_hard_pod_queue_row(
    *,
    hard_pod_pending: bool,
    custody_state: str,
    verification_state: str,
) -> bool:
    """Include in ``/pending/`` when work remains for the driver."""
    if hard_pod_pending:
        return True
    if verification_state != VERIFICATION_VERIFIED and custody_state not in {
        '',
        'not_started',
    }:
        return True
    return False


class HardPodProjectionService:
    """Shipment-centric Hard POD read projections."""

    def build_row(
        self,
        shipment: Any,
        *,
        driver: Any,
        tenant_schema: str,
        logs: list[Any] | None = None,
        custody_bundle: dict[str, Any] | None = None,
        portal_document: Any | None = None,
    ) -> dict[str, Any]:
        shipment_id = _shipment_pk(shipment)
        custody_bundle = custody_bundle or {}
        events = custody_bundle.get('events') or []
        receipt = custody_bundle.get('receipt')
        verification = custody_bundle.get('verification')
        submission = custody_bundle.get('submission')
        bundle_id = custody_bundle.get('bundle_id')

        verified_event_present = any(
            (getattr(e, 'event_type', None) or '').strip().casefold()
            == HardPODCustodySubmissionEvent.EventType.VERIFIED.casefold()
            for e in (events or [])
        )
        has_verification = verification is not None or verified_event_present
        custody_state = derive_custody_state(events, has_verification=has_verification)
        verification_state = (
            VERIFICATION_VERIFIED if has_verification else VERIFICATION_PENDING
        )

        log_evidence = log_evidence_flags(logs or [])
        column_flags = pod_cod_policy.derive_pod_cod_flags(shipment, driver=driver)
        hard_pod_pending = bool(column_flags.get('hard_pod_pending'))
        portal_pod = build_portal_snapshot(portal_document)

        reconciliation = reconcile_hard_pod_row(
            shipment=shipment,
            column_flags=column_flags,
            log_evidence=log_evidence,
            custody_state=custody_state,
            verification_state=verification_state,
            portal_pod=portal_pod,
        )

        return build_shipment_row(
            shipment=shipment,
            hard_pod_pending=hard_pod_pending,
            custody_state=custody_state,
            verification_state=verification_state,
            receiver=(
                build_receiver_block_from_submission(submission)
                if submission is not None
                else build_receiver_block(receipt)
            ),
            handoff=build_handoff_block(events),
            timeline_preview=build_timeline_preview(events),
            workflow_blocked=workflow_blocked_read_only(shipment),
            reconciliation={
                'custody_vs_workflow_mismatch': reconciliation[
                    'custody_vs_workflow_mismatch'
                ],
                'missing_hard_pod_log': reconciliation['missing_hard_pod_log'],
            },
            portal_pod=portal_pod,
            bundle_id=bundle_id,
            log_evidence=log_evidence,
        )

    def build_rows_for_shipments(
        self,
        shipments: list[Any],
        *,
        driver: Any,
        tenant_schema: str,
        pending_only: bool = True,
    ) -> list[dict[str, Any]]:
        shipment_ids = [_shipment_pk(s) for s in shipments if _shipment_pk(s)]
        logs_by_shipment = _load_action_logs_by_shipment(shipment_ids)
        custody_by_shipment = _load_custody_by_shipment(
            tenant_schema,
            shipment_ids,
            driver_id=_driver_pk(driver),
        )
        portal_by_shipment = _load_portal_pod_documents(shipment_ids)

        rows: list[dict[str, Any]] = []
        for shipment in shipments:
            sid = _shipment_pk(shipment)
            row = self.build_row(
                shipment,
                driver=driver,
                tenant_schema=tenant_schema,
                logs=logs_by_shipment.get(sid, []),
                custody_bundle=custody_by_shipment.get(sid),
                portal_document=portal_by_shipment.get(sid),
            )
            if pending_only and not is_pending_hard_pod_queue_row(
                hard_pod_pending=row['hard_pod_pending'],
                custody_state=row['custody_state'],
                verification_state=row['verification_state'],
            ):
                continue
            rows.append(row)
        return rows

    @staticmethod
    def assert_driver_may_view_shipment(driver: Any, shipment: Any) -> bool:
        booking = getattr(shipment, 'booking', None)
        return driver_owns_shipment_leg(driver, booking, shipment)
