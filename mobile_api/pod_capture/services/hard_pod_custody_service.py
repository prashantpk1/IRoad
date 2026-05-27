"""
mobile_api/pod_capture/services/hard_pod_custody_service.py

Append-only Hard POD custody chain (physical document lifecycle).
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from mobile_api.pod_capture.dto.staging_models import PODCaptureBundle
from mobile_api.pod_capture.models import (
    HardPODCustodyEvent,
    HardPODReceipt,
    HardPODVerification,
)


class HardPODCustodyService:
    """Record Hard POD custody events without mutating prior rows."""

    def record_collection(
        self,
        bundle: PODCaptureBundle,
        *,
        document_serial: str = '',
        document_reference: str = '',
        receiver_name: str = '',
        receiver_identity_ref: str = '',
        actor_id: str = '',
        actor_label: str = '',
    ) -> HardPODReceipt:
        receipt = HardPODReceipt.objects.create(
            bundle_id=bundle.bundle_id,
            tenant_schema=bundle.tenant_schema,
            shipment_id=bundle.shipment_id,
            driver_id=bundle.driver_id,
            document_serial=(document_serial or '').strip(),
            document_reference=(document_reference or '').strip(),
            receiver_name=(receiver_name or '').strip(),
            receiver_identity_ref=(receiver_identity_ref or '').strip(),
            collected_at=timezone.now(),
        )
        HardPODCustodyEvent.objects.create(
            bundle_id=bundle.bundle_id,
            receipt=receipt,
            tenant_schema=bundle.tenant_schema,
            shipment_id=bundle.shipment_id,
            event_type=HardPODCustodyEvent.EventType.COLLECTED,
            actor_id=actor_id,
            actor_label=actor_label,
            occurred_at=receipt.collected_at,
        )
        return receipt

    def record_received(
        self,
        receipt: HardPODReceipt,
        *,
        actor_id: str = '',
        actor_label: str = '',
    ) -> HardPODCustodyEvent:
        now = timezone.now()
        HardPODReceipt.objects.filter(pk=receipt.pk).update(received_at=now)
        return HardPODCustodyEvent.objects.create(
            bundle_id=receipt.bundle_id,
            receipt=receipt,
            tenant_schema=receipt.tenant_schema,
            shipment_id=receipt.shipment_id,
            event_type=HardPODCustodyEvent.EventType.RECEIVED,
            actor_id=actor_id,
            actor_label=actor_label,
            occurred_at=now,
        )

    def record_handoff(
        self,
        bundle: PODCaptureBundle,
        *,
        handoff_to: str,
        actor_id: str = '',
        actor_label: str = '',
        notes: str = '',
    ) -> HardPODCustodyEvent:
        return HardPODCustodyEvent.objects.create(
            bundle_id=bundle.bundle_id,
            tenant_schema=bundle.tenant_schema,
            shipment_id=bundle.shipment_id,
            event_type=HardPODCustodyEvent.EventType.HANDOFF,
            actor_id=actor_id,
            actor_label=actor_label,
            handoff_to=(handoff_to or '').strip(),
            notes=(notes or '').strip(),
            occurred_at=timezone.now(),
        )

    def record_supervisor_verification(
        self,
        bundle: PODCaptureBundle,
        *,
        supervisor_id: str = '',
        supervisor_label: str = '',
        verification_notes: str = '',
    ) -> HardPODVerification:
        verification = HardPODVerification.objects.create(
            bundle_id=bundle.bundle_id,
            tenant_schema=bundle.tenant_schema,
            shipment_id=bundle.shipment_id,
            supervisor_id=supervisor_id,
            supervisor_label=supervisor_label,
            verification_notes=verification_notes,
        )
        HardPODCustodyEvent.objects.create(
            bundle_id=bundle.bundle_id,
            tenant_schema=bundle.tenant_schema,
            shipment_id=bundle.shipment_id,
            event_type=HardPODCustodyEvent.EventType.VERIFIED,
            actor_id=supervisor_id,
            actor_label=supervisor_label,
            occurred_at=verification.verified_at,
        )
        return verification

    def timeline_entries_for_bundle(self, bundle_id: str) -> list[dict[str, Any]]:
        events = HardPODCustodyEvent.objects.filter(bundle_id=bundle_id).order_by(
            'occurred_at', 'created_at'
        )
        return [
            {
                'event_type': e.event_type,
                'occurred_at': e.occurred_at,
                'actor_label': e.actor_label,
                'handoff_to': e.handoff_to,
                'notes': e.notes,
            }
            for e in events
        ]
