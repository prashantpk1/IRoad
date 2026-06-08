"""
mobile_api/hard_pod/models.py

Durable Hard POD custody submissions (public schema, append-only events).
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class HardPODCustodySubmission(models.Model):
    """
    One driver custody submit session (idempotent on client_submission_id).

    Prepares custody state only — does not mutate shipment workflow columns.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    client_submission_id = models.CharField(max_length=128)
    capture_bundle_id = models.UUIDField(null=True, blank=True, db_index=True)
    receiver_name = models.CharField(max_length=200, blank=True, default='')
    receiver_contact = models.CharField(max_length=128, blank=True, default='')
    handoff_notes = models.TextField(blank=True, default='')
    latitude = models.CharField(max_length=32, blank=True, default='')
    longitude = models.CharField(max_length=32, blank=True, default='')
    # Metadata-only integrity checksum for replay safety.
    integrity_checksum = models.CharField(max_length=64, blank=True, default='')
    # Promotion binding: set by Execute Action hard-pod side effects.
    promoted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    promotion_action_log_id = models.CharField(max_length=64, blank=True, default='')
    submitted_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mobile_hard_pod_custody_submission'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(
                fields=['tenant_schema', 'shipment_id', 'submitted_at'],
                name='hard_pod_sub_tenant_ship',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'driver_id', 'client_submission_id'],
                name='hard_pod_submission_idempotency_uq',
            ),
        ]

    def __str__(self) -> str:
        return f'HardPODCustodySubmission({self.id})'

    def save(self, *args, **kwargs) -> None:
        """
        Enforce custody header immutability after verification/promotion.

        The only allowed post-verified mutation is the one-time promotion linkage
        used by Execute Action hard-pod side effects.
        """
        from mobile_api.hard_pod.guards.immutable_custody_guard import (
            assert_custody_header_mutable,
        )

        assert_custody_header_mutable(
            self,
            update_fields=kwargs.get('update_fields'),
        )
        super().save(*args, **kwargs)


class HardPODConfirmedPage(models.Model):
    """Immutable per-page physical custody confirmation for one submit session."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        HardPODCustodySubmission,
        on_delete=models.CASCADE,
        related_name='confirmed_pages',
    )
    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    document_id = models.CharField(max_length=64, blank=True, default='')
    page_id = models.CharField(max_length=64, blank=True, default='')
    line_no = models.PositiveIntegerField(default=1)
    physical_page_no = models.PositiveIntegerField(default=1)
    label = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mobile_hard_pod_confirmed_page'
        ordering = ['line_no', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['submission', 'document_id', 'line_no'],
                name='hard_pod_confirmed_page_uq',
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.pk and HardPODConfirmedPage.objects.filter(pk=self.pk).exists():
            raise ValueError('Hard POD confirmed pages are immutable and cannot be updated.')
        if self.submission_id:
            sub = self.submission
            self.tenant_schema = sub.tenant_schema
            self.shipment_id = sub.shipment_id
            self.driver_id = sub.driver_id
        super().save(*args, **kwargs)


class HardPODCustodySubmissionMedia(models.Model):
    """Immutable media evidence linked to a custody submission."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        HardPODCustodySubmission,
        on_delete=models.CASCADE,
        related_name='media_rows',
    )
    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    media_type = models.CharField(max_length=32, blank=True, default='')
    file_ref = models.CharField(max_length=500)
    file_ref_normalized = models.CharField(max_length=500, db_index=True)
    file_name = models.CharField(max_length=255, blank=True, default='')
    mime_type = models.CharField(max_length=128, blank=True, default='')
    checksum = models.CharField(max_length=128, blank=True, default='')
    line_no = models.PositiveIntegerField(default=1)
    captured_at = models.DateTimeField(null=True, blank=True)
    immutable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mobile_hard_pod_custody_submission_media'
        ordering = ['line_no', 'created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'file_ref_normalized'],
                name='hard_pod_sub_media_file_ref_uq',
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.pk and HardPODCustodySubmissionMedia.objects.filter(pk=self.pk).exists():
            raise ValueError(
                'Hard POD custody submission media is immutable and cannot be updated.'
            )
        self.file_ref_normalized = (self.file_ref or '').replace('\\', '/').lstrip('/')
        if self.submission_id:
            if not self.tenant_schema:
                self.tenant_schema = self.submission.tenant_schema
            if not self.shipment_id:
                self.shipment_id = self.submission.shipment_id
            if not self.driver_id:
                self.driver_id = self.submission.driver_id
        super().save(*args, **kwargs)


class HardPODCustodySubmissionEvent(models.Model):
    """Append-only custody chain event for a submission."""

    class EventType(models.TextChoices):
        COLLECTED = 'collected', 'Driver collected'
        RECEIVED = 'received', 'Physical received'
        HANDOFF = 'handoff', 'Custody handoff'
        TRANSFERRED = 'transferred', 'Transferred'
        VERIFIED = 'verified', 'Verified'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        HardPODCustodySubmission,
        on_delete=models.CASCADE,
        related_name='custody_events',
    )
    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    actor_id = models.CharField(max_length=64, blank=True, default='')
    actor_label = models.CharField(max_length=200, blank=True, default='')
    handoff_to = models.CharField(max_length=200, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    latitude = models.CharField(max_length=32, blank=True, default='')
    longitude = models.CharField(max_length=32, blank=True, default='')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'mobile_hard_pod_custody_submission_event'
        ordering = ['occurred_at', 'created_at']

    def save(self, *args, **kwargs) -> None:
        if self.pk and HardPODCustodySubmissionEvent.objects.filter(pk=self.pk).exists():
            raise ValueError('Hard POD custody events are append-only and cannot be updated.')
        if self.submission_id:
            sub = self.submission
            self.tenant_schema = sub.tenant_schema
            self.shipment_id = sub.shipment_id
            self.driver_id = sub.driver_id
        super().save(*args, **kwargs)
