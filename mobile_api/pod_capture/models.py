"""
mobile_api/pod_capture/models.py

Durable POD evidence staging, promotion audit, and Hard POD custody (public schema).
"""
from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class PODCaptureBundle(models.Model):
    """Durable staged POD evidence bundle (HA-safe, worker-safe)."""

    class BundleStatus(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        READY = 'ready', 'Ready'
        PROMOTED = 'promoted', 'Promoted'
        EXPIRED = 'expired', 'Expired'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    client_capture_id = models.CharField(max_length=128)
    workflow_version = models.CharField(max_length=256, blank=True, default='')
    content_hash = models.CharField(max_length=128, blank=True, default='')
    bundle_status = models.CharField(
        max_length=16,
        choices=BundleStatus.choices,
        default=BundleStatus.DRAFT,
        db_index=True,
    )
    pod_type = models.CharField(max_length=32, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    latitude = models.CharField(max_length=32, blank=True, default='')
    longitude = models.CharField(max_length=32, blank=True, default='')
    media_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)
    promoted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    promotion_action_log_id = models.CharField(max_length=64, blank=True, default='')
    replayed_from_bundle_id = models.UUIDField(null=True, blank=True)
    integrity_checksum = models.CharField(max_length=64, blank=True, default='')
    capture_device_id = models.CharField(max_length=128, blank=True, default='')
    capture_app_version = models.CharField(max_length=64, blank=True, default='')
    rejected_reason = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        db_table = 'mobile_pod_capture_bundle'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['tenant_schema', 'shipment_id', 'bundle_status'],
                name='pod_cap_tenant_ship_status',
            ),
            models.Index(
                fields=['tenant_schema', 'driver_id', 'created_at'],
                name='pod_cap_tenant_drv_created',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'driver_id', 'client_capture_id'],
                name='pod_capture_bundle_idempotency_uq',
            ),
        ]

    def __str__(self) -> str:
        return f'PODCaptureBundle({self.id})'


class PODCaptureMedia(models.Model):
    """One staged media file under a bundle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(
        PODCaptureBundle,
        on_delete=models.CASCADE,
        related_name='media_rows',
    )
    media_type = models.CharField(max_length=32, blank=True, default='')
    file_ref = models.CharField(max_length=500)
    file_ref_normalized = models.CharField(max_length=500, db_index=True)
    mime_type = models.CharField(max_length=128, blank=True, default='')
    checksum = models.CharField(max_length=128, blank=True, default='')
    line_no = models.PositiveIntegerField(default=1)
    file_name = models.CharField(max_length=255, blank=True, default='')
    description = models.CharField(max_length=255, blank=True, default='')
    captured_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)
    immutable = models.BooleanField(default=False)
    promoted = models.BooleanField(default=False, db_index=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    promoted_action_log_id = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        db_table = 'mobile_pod_capture_media'
        ordering = ['line_no', 'uploaded_at']
        indexes = [
            models.Index(fields=['bundle', 'promoted'], name='pod_cap_media_bundle_prom'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_schema', 'file_ref_normalized'],
                name='pod_capture_file_ref_uq',
            ),
        ]

    tenant_schema = models.CharField(max_length=100, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    client_capture_id = models.CharField(max_length=128, blank=True, default='')

    def save(self, *args, **kwargs) -> None:
        self.file_ref_normalized = (self.file_ref or '').replace('\\', '/').lstrip('/')
        if self.bundle_id and not self.tenant_schema:
            bundle = self.bundle
            self.tenant_schema = bundle.tenant_schema
            self.shipment_id = bundle.shipment_id
            self.driver_id = bundle.driver_id
            self.client_capture_id = bundle.client_capture_id
        super().save(*args, **kwargs)


class PODCapturePromotionAudit(models.Model):
    """Forensic record of bundle → Action Log promotion."""

    class PromotionType(models.TextChoices):
        INITIAL = 'initial', 'Initial'
        REPLAY = 'replay', 'Replay'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(
        PODCaptureBundle,
        on_delete=models.PROTECT,
        related_name='promotion_audits',
    )
    action_log_id = models.CharField(max_length=64, db_index=True)
    shipment_id = models.CharField(max_length=64, db_index=True)
    driver_id = models.CharField(max_length=64, db_index=True)
    tenant_schema = models.CharField(max_length=100, db_index=True)
    promoted_at = models.DateTimeField(default=timezone.now, db_index=True)
    promoted_by = models.CharField(max_length=128, blank=True, default='')
    promotion_type = models.CharField(
        max_length=16,
        choices=PromotionType.choices,
        default=PromotionType.INITIAL,
    )
    execution_idempotency_key = models.CharField(max_length=128, blank=True, default='')
    replay_source = models.BooleanField(default=False)
    bundle_integrity_checksum = models.CharField(max_length=64, blank=True, default='')
    capture_device_id = models.CharField(max_length=128, blank=True, default='')
    capture_app_version = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        db_table = 'mobile_pod_capture_promotion_audit'
        ordering = ['-promoted_at']
        indexes = [
            models.Index(
                fields=['bundle', 'action_log_id'],
                name='pod_cap_promo_bundle_log',
            ),
        ]


