"""
mobile_api/hard_pod/services/hard_pod_custody_service.py

Append-only Hard POD custody events and immutable media evidence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from mobile_api.hard_pod.models import (
    HardPODConfirmedPage,
    HardPODCustodySubmission,
    HardPODCustodySubmissionEvent,
    HardPODCustodySubmissionMedia,
)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, 'isoformat') else str(dt)


class HardPodCustodyService:
    """Record custody evidence — append-only events, immutable media."""

    def append_event(
        self,
        submission: HardPODCustodySubmission,
        *,
        event_type: str,
        actor_id: str = '',
        actor_label: str = '',
        handoff_to: str = '',
        notes: str = '',
        latitude: str = '',
        longitude: str = '',
        occurred_at: datetime | None = None,
    ) -> HardPODCustodySubmissionEvent:
        return HardPODCustodySubmissionEvent.objects.create(
            submission=submission,
            tenant_schema=submission.tenant_schema,
            shipment_id=submission.shipment_id,
            driver_id=submission.driver_id,
            event_type=event_type,
            actor_id=(actor_id or '').strip(),
            actor_label=(actor_label or '').strip(),
            handoff_to=(handoff_to or '').strip(),
            notes=(notes or '').strip(),
            latitude=(latitude or '').strip() or submission.latitude,
            longitude=(longitude or '').strip() or submission.longitude,
            occurred_at=occurred_at or timezone.now(),
        )

    def persist_confirmed_pages(
        self,
        submission: HardPODCustodySubmission,
        confirmed_pages: list[dict[str, Any]],
    ) -> list[HardPODConfirmedPage]:
        rows: list[HardPODConfirmedPage] = []
        for page in confirmed_pages:
            rows.append(
                HardPODConfirmedPage.objects.create(
                    submission=submission,
                    tenant_schema=submission.tenant_schema,
                    shipment_id=submission.shipment_id,
                    driver_id=submission.driver_id,
                    document_id=(page.get('document_id') or '').strip(),
                    page_id=(page.get('page_id') or '').strip(),
                    line_no=int(page.get('line_no') or 1),
                    physical_page_no=int(page.get('physical_page_no') or 1),
                    label=(page.get('label') or '').strip(),
                )
            )
        return rows

    def persist_media_rows(
        self,
        submission: HardPODCustodySubmission,
        media_items: list[dict[str, Any]],
    ) -> list[HardPODCustodySubmissionMedia]:
        rows: list[HardPODCustodySubmissionMedia] = []
        for idx, item in enumerate(media_items, start=1):
            file_ref = (item.get('file_ref') or '').strip()
            if not file_ref:
                continue
            rows.append(
                HardPODCustodySubmissionMedia.objects.create(
                    submission=submission,
                    tenant_schema=submission.tenant_schema,
                    shipment_id=submission.shipment_id,
                    driver_id=submission.driver_id,
                    media_type=(item.get('media_type') or '').strip(),
                    file_ref=file_ref,
                    file_name=(item.get('file_name') or '').strip(),
                    mime_type=(item.get('mime_type') or '').strip(),
                    checksum=(item.get('checksum') or '').strip(),
                    line_no=int(item.get('sort_order') or item.get('line_no') or idx),
                    captured_at=item.get('captured_at'),
                    immutable=True,
                )
            )
        return rows

    def record_collected(
        self,
        submission: HardPODCustodySubmission,
        *,
        actor_id: str,
        actor_label: str,
    ) -> HardPODCustodySubmissionEvent:
        return self.append_event(
            submission,
            event_type=HardPODCustodySubmissionEvent.EventType.COLLECTED,
            actor_id=actor_id,
            actor_label=actor_label,
            notes='',
        )

    def record_handoff(
        self,
        submission: HardPODCustodySubmission,
        *,
        actor_id: str,
        actor_label: str,
    ) -> HardPODCustodySubmissionEvent:
        notes = (submission.handoff_notes or '').strip()
        return self.append_event(
            submission,
            event_type=HardPODCustodySubmissionEvent.EventType.HANDOFF,
            actor_id=actor_id,
            actor_label=actor_label,
            notes=notes,
            handoff_to=(submission.receiver_name or '').strip(),
        )

    def record_received(
        self,
        submission: HardPODCustodySubmission,
        *,
        actor_label: str,
    ) -> HardPODCustodySubmissionEvent:
        return self.append_event(
            submission,
            event_type=HardPODCustodySubmissionEvent.EventType.RECEIVED,
            actor_id='',
            actor_label=(actor_label or '').strip() or (submission.receiver_name or '').strip(),
            notes='',
        )

    def record_verified(
        self,
        submission: HardPODCustodySubmission,
        *,
        actor_label: str,
    ) -> HardPODCustodySubmissionEvent:
        return self.append_event(
            submission,
            event_type=HardPODCustodySubmissionEvent.EventType.VERIFIED,
            actor_id='',
            actor_label=(actor_label or '').strip() or (submission.receiver_name or '').strip(),
            notes='',
        )

    def timeline_preview(
        self,
        submission: HardPODCustodySubmission,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        events.append(
            {
                'event_type': 'submitted',
                'occurred_at': _iso(submission.submitted_at),
                'actor_label': (submission.receiver_name or '').strip() or (submission.driver_id or '').strip(),
                'handoff_to': '',
                'notes': '',
                'latitude': submission.latitude,
                'longitude': submission.longitude,
            }
        )
        events.extend(
            {
                'event_type': e.event_type,
                'occurred_at': _iso(e.occurred_at),
                'actor_label': e.actor_label,
                'handoff_to': e.handoff_to,
                'notes': e.notes,
                'latitude': e.latitude,
                'longitude': e.longitude,
            }
            for e in submission.custody_events.order_by('occurred_at', 'created_at')
        )
        if submission.promoted_at or (submission.promotion_action_log_id or '').strip():
            events.append(
                {
                    'event_type': 'promoted',
                    'occurred_at': _iso(submission.promoted_at),
                    'actor_label': (submission.promotion_action_log_id or '').strip(),
                    'handoff_to': '',
                    'notes': '',
                    'latitude': submission.latitude,
                    'longitude': submission.longitude,
                }
            )
        ordered = events[:limit]
        return [
            {
                'event_type': row['event_type'],
                'occurred_at': row['occurred_at'],
                'actor_label': row['actor_label'],
                'handoff_to': row['handoff_to'],
                'notes': row['notes'],
                'latitude': row['latitude'],
                'longitude': row['longitude'],
            }
            for row in ordered
        ]

    def build_submission_payload(
        self,
        submission: HardPODCustodySubmission,
        *,
        replayed: bool,
        media_rows: list[HardPODCustodySubmissionMedia] | None = None,
    ) -> dict[str, Any]:
        media_rows = media_rows if media_rows is not None else list(
            submission.media_rows.order_by('line_no')
        )
        confirmed_pages = list(submission.confirmed_pages.order_by('line_no', 'created_at'))
        events = list(submission.custody_events.order_by('occurred_at', 'created_at'))
        return {
            'submission_id': str(submission.id),
            'client_submission_id': submission.client_submission_id,
            'shipment_id': submission.shipment_id,
            'driver_id': submission.driver_id,
            'tenant_schema': submission.tenant_schema,
            'receiver_name': submission.receiver_name,
            'receiver_contact': submission.receiver_contact,
            'handoff_notes': submission.handoff_notes,
            'latitude': submission.latitude,
            'longitude': submission.longitude,
            'submitted_at': _iso(submission.submitted_at),
            'capture_bundle_id': (
                str(submission.capture_bundle_id) if submission.capture_bundle_id else None
            ),
            'replayed': replayed,
            'confirmed_page_count': len(confirmed_pages),
            'confirmed_pages': [
                {
                    'page_id': (p.page_id or '').strip(),
                    'document_id': (p.document_id or '').strip(),
                    'line_no': p.line_no,
                    'physical_page_no': p.physical_page_no,
                    'label': (p.label or '').strip(),
                }
                for p in confirmed_pages
            ],
            'media_count': len(media_rows),
            'media': [
                {
                    'media_id': str(m.id),
                    'media_type': m.media_type,
                    'file_ref': m.file_ref,
                    'immutable': m.immutable,
                }
                for m in media_rows
            ],
            'event_count': len(events),
            'custody_state': (
                'promoted'
                if submission.promoted_at or (submission.promotion_action_log_id or '').strip()
                else (events[-1].event_type if events else 'submitted')
            ),
        }
