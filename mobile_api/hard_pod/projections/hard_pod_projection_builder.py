"""
mobile_api/hard_pod/projections/hard_pod_projection_builder.py

Shipment-centric Hard POD list row assembly (pure dict building).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from mobile_api.pod_capture.models import HardPODCustodyEvent

CUSTODY_NOT_STARTED = 'not_started'
CUSTODY_COLLECTED = 'collected'
CUSTODY_RECEIVED = 'received'
CUSTODY_HANDOFF = 'handoff'
CUSTODY_TRANSFERRED = 'transferred'
CUSTODY_VERIFIED = 'verified'

VERIFICATION_PENDING = 'pending'
VERIFICATION_VERIFIED = 'verified'

_EVENT_RANK = {
    HardPODCustodyEvent.EventType.COLLECTED: 1,
    HardPODCustodyEvent.EventType.RECEIVED: 2,
    HardPODCustodyEvent.EventType.HANDOFF: 3,
    HardPODCustodyEvent.EventType.TRANSFERRED: 4,
    HardPODCustodyEvent.EventType.VERIFIED: 5,
}

_CUSTODY_STATE_FROM_EVENT = {
    HardPODCustodyEvent.EventType.COLLECTED: CUSTODY_COLLECTED,
    HardPODCustodyEvent.EventType.RECEIVED: CUSTODY_RECEIVED,
    HardPODCustodyEvent.EventType.HANDOFF: CUSTODY_HANDOFF,
    HardPODCustodyEvent.EventType.TRANSFERRED: CUSTODY_TRANSFERRED,
    HardPODCustodyEvent.EventType.VERIFIED: CUSTODY_VERIFIED,
}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if hasattr(dt, 'isoformat'):
        return dt.isoformat()
    return str(dt)


def derive_custody_state(
    events: list[Any],
    *,
    has_verification: bool,
) -> str:
    if has_verification:
        return CUSTODY_VERIFIED
    if not events:
        return CUSTODY_NOT_STARTED

    best_rank = 0
    best_state = CUSTODY_NOT_STARTED
    for event in events:
        event_type = getattr(event, 'event_type', None) or (
            event.get('event_type') if isinstance(event, dict) else ''
        )
        rank = _EVENT_RANK.get(event_type, 0)
        if rank >= best_rank:
            best_rank = rank
            best_state = _CUSTODY_STATE_FROM_EVENT.get(event_type, best_state)
    return best_state


def derive_collection_progress(custody_state: str) -> int:
    mapping = {
        CUSTODY_NOT_STARTED: 0,
        CUSTODY_COLLECTED: 25,
        CUSTODY_RECEIVED: 50,
        CUSTODY_HANDOFF: 75,
        CUSTODY_TRANSFERRED: 85,
        CUSTODY_VERIFIED: 100,
    }
    return mapping.get(custody_state, 0)


def build_receiver_block(receipt: Any | None) -> dict[str, Any]:
    if receipt is None:
        return {}
    return {
        'name': (getattr(receipt, 'receiver_name', None) or '').strip(),
        'identity_ref': (getattr(receipt, 'receiver_identity_ref', None) or '').strip(),
        'document_serial': (getattr(receipt, 'document_serial', None) or '').strip(),
        'document_reference': (getattr(receipt, 'document_reference', None) or '').strip(),
        'collected_at': _iso(getattr(receipt, 'collected_at', None)),
        'received_at': _iso(getattr(receipt, 'received_at', None)),
    }


def build_receiver_block_from_submission(submission: Any | None) -> dict[str, Any]:
    if submission is None:
        return {}
    return {
        'name': (getattr(submission, 'receiver_name', None) or '').strip(),
        'identity_ref': '',
        'contact': (getattr(submission, 'receiver_contact', None) or '').strip(),
        'document_serial': '',
        'document_reference': '',
        'collected_at': _iso(getattr(submission, 'submitted_at', None)),
        'received_at': _iso(getattr(submission, 'submitted_at', None)),
    }


def build_handoff_block(events: list[Any]) -> dict[str, Any]:
    handoff_events = [
        e
        for e in events
        if (getattr(e, 'event_type', None) or '') == HardPODCustodyEvent.EventType.HANDOFF
    ]
    if not handoff_events:
        return {}
    latest = handoff_events[-1]
    return {
        'handoff_to': (getattr(latest, 'handoff_to', None) or '').strip(),
        'actor_label': (getattr(latest, 'actor_label', None) or '').strip(),
        'occurred_at': _iso(getattr(latest, 'occurred_at', None)),
        'notes': (getattr(latest, 'notes', None) or '').strip(),
    }


def build_timeline_preview(
    custody_events: list[Any],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in custody_events[-limit:]:
        rows.append(
            {
                'source': 'custody',
                'event_type': getattr(event, 'event_type', '') or '',
                'occurred_at': _iso(getattr(event, 'occurred_at', None)),
                'actor_label': (getattr(event, 'actor_label', None) or '').strip(),
                'handoff_to': (getattr(event, 'handoff_to', None) or '').strip(),
            }
        )
    return rows


def build_portal_snapshot(document: Any | None) -> dict[str, Any]:
    if document is None:
        return {}
    return {
        'document_id': str(getattr(document, 'pk', '') or ''),
        'physical_location': (getattr(document, 'physical_location', None) or '').strip(),
        'status': (getattr(document, 'status', None) or '').strip(),
        'document_ref_no': (getattr(document, 'document_ref_no', None) or '').strip(),
    }


def build_shipment_row(
    *,
    shipment: Any,
    hard_pod_pending: bool,
    custody_state: str,
    verification_state: str,
    receiver: dict[str, Any],
    handoff: dict[str, Any],
    timeline_preview: list[dict[str, Any]],
    workflow_blocked: bool,
    reconciliation: dict[str, bool],
    portal_pod: dict[str, Any],
    bundle_id: str | None = None,
    log_evidence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    shipment_pk = str(getattr(shipment, 'pk', '') or getattr(shipment, 'shipment_id', ''))
    job_no = (
        (getattr(shipment, 'shipment_no', None) or '').strip()
        or shipment_pk
    )
    return {
        'shipment_id': shipment_pk,
        'job_no': job_no,
        'hard_pod_pending': hard_pod_pending,
        'custody_state': custody_state,
        'verification_state': verification_state,
        'collection_progress': derive_collection_progress(custody_state),
        'receiver': receiver,
        'handoff': handoff,
        'timeline_preview': timeline_preview,
        'workflow_blocked': workflow_blocked,
        'reconciliation': reconciliation,
        'portal_pod': portal_pod,
        'capture_bundle_id': bundle_id,
        'log_evidence': dict(log_evidence or {}),
        'pod_status': (getattr(shipment, 'pod_status', None) or '').strip(),
        'shipment_status': (getattr(shipment, 'shipment_status', None) or '').strip(),
    }
