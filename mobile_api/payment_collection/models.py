"""
mobile_api/payment_collection/models.py

Durable payment collection staging models (public mobile_api schema).
Append-only evidence rows; replay-safe bundles.
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class PaymentCollectionBundle(models.Model):
    """Durable bundle header for a driver payment collection evidence session."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    client_payment_id = models.CharField(max_length=128)

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2)
    variance_detected = models.BooleanField(default=False, db_index=True)

    payment_mode = models.CharField(max_length=32, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    integrity_checksum = models.CharField(max_length=64, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Reserved for future Execute-time promotion linkage.
    promoted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    promotion_action_log_id = models.CharField(max_length=64, blank=True, default='')
    replayed_from_bundle_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = 'mobile_payment_collection_bundle'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant_schema', 'driver_id', 'shipment_id'], name='mpcb_scope_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'driver_id', 'client_payment_id'],
                name='mobile_payment_bundle_idempotency_uq',
            ),
        ]

    def __str__(self) -> str:
        return f'PaymentCollectionBundle({self.id})'


class PaymentCollectionEvidence(models.Model):
    """Immutable proof media evidence linked to a payment collection bundle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(
        PaymentCollectionBundle,
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
        db_table = 'mobile_payment_collection_evidence'
        ordering = ['line_no', 'uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'file_ref_normalized'],
                name='mobile_payment_evidence_file_ref_uq',
            ),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.pk and PaymentCollectionEvidence.objects.filter(pk=self.pk).exists():
            raise ValueError('Payment evidence is immutable and cannot be updated.')
        self.file_ref_normalized = (self.file_ref or '').replace('\\', '/').lstrip('/')
        if not self.tenant_schema and self.bundle_id:
            self.tenant_schema = self.bundle.tenant_schema
        if not self.shipment_id and self.bundle_id:
            self.shipment_id = self.bundle.shipment_id
        if not self.driver_id and self.bundle_id:
            self.driver_id = self.bundle.driver_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'PaymentCollectionEvidence({self.id})'


class PaymentCollectionAudit(models.Model):
    """Forensic audit record for payment collection staging."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(
        PaymentCollectionBundle,
        on_delete=models.CASCADE,
        related_name='audits',
    )

    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)

    # Reserved for promotion linkage when Execute Action consumes evidence.
    action_log_id = models.CharField(max_length=64, blank=True, default='')
    execution_idempotency_key = models.CharField(max_length=128, blank=True, default='')
    replay_source = models.BooleanField(default=False)

    # Capture evidence metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    promoted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'mobile_payment_collection_audit'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant_schema', 'shipment_id', 'driver_id'], name='mpca_scope_idx'),
        ]

    def __str__(self) -> str:
        return f'PaymentCollectionAudit({self.id})'

