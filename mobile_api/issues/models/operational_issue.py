"""
mobile_api/issues/models/operational_issue.py

Durable operational exception domain (public mobile_api schema).
Append-only escalation events and immutable evidence.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class OperationalIssue(models.Model):
    """Driver-reported operational exception (prep-only; no workflow mutation)."""

    class IssueType(models.TextChoices):
        DELAY = 'delay', 'Delay'
        VEHICLE_BREAKDOWN = 'vehicle_breakdown', 'Vehicle breakdown'
        CUSTOMER_UNAVAILABLE = 'customer_unavailable', 'Customer unavailable'
        PAYMENT_DISPUTE = 'payment_dispute', 'Payment dispute'
        POD_ISSUE = 'pod_issue', 'POD issue'
        ACCIDENT = 'accident', 'Accident'
        ROUTE_BLOCKED = 'route_blocked', 'Route blocked'
        OTHER = 'other', 'Other'

    class Severity(models.TextChoices):
        LOW = 'low', 'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH = 'high', 'High'
        CRITICAL = 'critical', 'Critical'

    class EscalationState(models.TextChoices):
        OPEN = 'open', 'Open'
        ESCALATED = 'escalated', 'Escalated'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
        RESOLVED = 'resolved', 'Resolved'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    client_issue_id = models.CharField(max_length=128)

    issue_type = models.CharField(max_length=32, choices=IssueType.choices, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, db_index=True)
    notes = models.TextField(blank=True, default='')

    escalation_state = models.CharField(
        max_length=16,
        choices=EscalationState.choices,
        default=EscalationState.OPEN,
        db_index=True,
    )
    blocking_recommended = models.BooleanField(default=False, db_index=True)

    latitude = models.CharField(max_length=32, blank=True, default='')
    longitude = models.CharField(max_length=32, blank=True, default='')
    integrity_checksum = models.CharField(max_length=64, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'mobile_operational_issue'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['tenant_schema', 'shipment_id', 'escalation_state'],
                name='moi_tenant_ship_state_idx',
            ),
            models.Index(
                fields=['tenant_schema', 'driver_id', 'created_at'],
                name='moi_tenant_drv_created_idx',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'driver_id', 'client_issue_id'],
                name='mobile_operational_issue_idempotency_uq',
            ),
        ]

    def __str__(self) -> str:
        return f'OperationalIssue({self.id})'

    @property
    def is_unresolved(self) -> bool:
        return self.escalation_state not in {
            self.EscalationState.RESOLVED,
            self.EscalationState.REJECTED,
        }


class OperationalIssueEvidence(models.Model):
    """Immutable issue media evidence linked to an operational issue."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(
        OperationalIssue,
        on_delete=models.CASCADE,
        related_name='evidence_rows',
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
    uploaded_at = models.DateTimeField(default=timezone.now)
    immutable = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'mobile_operational_issue_evidence'
        ordering = ['line_no', 'uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'file_ref_normalized'],
                name='mobile_issue_evidence_file_ref_uq',
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.pk and OperationalIssueEvidence.objects.filter(pk=self.pk).exists():
            raise ValueError('Issue evidence is immutable and cannot be updated.')
        self.file_ref_normalized = (self.file_ref or '').replace('\\', '/').lstrip('/')
        if self.issue_id:
            if not self.tenant_schema:
                self.tenant_schema = self.issue.tenant_schema
            if not self.shipment_id:
                self.shipment_id = self.issue.shipment_id
            if not self.driver_id:
                self.driver_id = self.issue.driver_id
        super().save(*args, **kwargs)


class OperationalIssueEscalationEvent(models.Model):
    """Append-only escalation lifecycle event."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(
        OperationalIssue,
        on_delete=models.CASCADE,
        related_name='escalation_events',
    )

    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)

    from_state = models.CharField(max_length=16, blank=True, default='')
    to_state = models.CharField(max_length=16, db_index=True)
    event_type = models.CharField(max_length=32, db_index=True)
    notes = models.TextField(blank=True, default='')
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'mobile_operational_issue_escalation_event'
        ordering = ['recorded_at', 'id']

    def save(self, *args, **kwargs) -> None:
        if self.pk and OperationalIssueEscalationEvent.objects.filter(pk=self.pk).exists():
            raise ValueError('Escalation events are append-only and cannot be updated.')
        if self.issue_id:
            if not self.tenant_schema:
                self.tenant_schema = self.issue.tenant_schema
            if not self.shipment_id:
                self.shipment_id = self.issue.shipment_id
            if not self.driver_id:
                self.driver_id = self.issue.driver_id
        super().save(*args, **kwargs)


class IssueLifecycleEvent(OperationalIssueEscalationEvent):
    """Proxy view of issue lifecycle events for lifecycle-specific orchestration."""

    class Meta:
        proxy = True
        verbose_name = 'Issue lifecycle event'
        verbose_name_plural = 'Issue lifecycle events'


class OperationalIssueTimelineEntry(models.Model):
    """Denormalized timeline preview row for mobile job detail projection."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(
        OperationalIssue,
        on_delete=models.CASCADE,
        related_name='timeline_entries',
    )

    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)

    event_category = models.CharField(max_length=32, default='issue')
    event_type = models.CharField(max_length=32, db_index=True)
    title = models.CharField(max_length=200, blank=True, default='')
    summary = models.TextField(blank=True, default='')
    severity = models.CharField(max_length=16, blank=True, default='')
    escalation_state = models.CharField(max_length=16, blank=True, default='')
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'mobile_operational_issue_timeline_entry'
        ordering = ['-recorded_at']

    def save(self, *args, **kwargs) -> None:
        if self.pk and OperationalIssueTimelineEntry.objects.filter(pk=self.pk).exists():
            raise ValueError('Issue timeline entries are append-only and cannot be updated.')
        if self.issue_id:
            if not self.tenant_schema:
                self.tenant_schema = self.issue.tenant_schema
            if not self.shipment_id:
                self.shipment_id = self.issue.shipment_id
            if not self.driver_id:
                self.driver_id = self.issue.driver_id
        super().save(*args, **kwargs)
