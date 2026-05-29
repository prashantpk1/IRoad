"""
mobile_api/job_detail/serializers/job_detail_serializer.py

DRF validation shell for the unified Job Detail ``data`` payload.
"""
from __future__ import annotations

from rest_framework import serializers


class JobDetailJobSerializer(serializers.Serializer):
    """Nested ``job`` — TODO: explicit fields when contract stabilizes."""


class JobDetailWorkflowSerializer(serializers.Serializer):
    """Nested ``workflow``."""


class JobDetailTimelineSerializer(serializers.Serializer):
    """Nested ``timeline``."""


class JobDetailPodCodSerializer(serializers.Serializer):
    """Nested ``pod_cod`` (shipment only)."""


class JobDetailRoundTripSerializer(serializers.Serializer):
    """Nested ``round_trip`` (shipment only)."""


class JobDetailAlertsSerializer(serializers.Serializer):
    """Nested ``alerts``."""


class JobDetailSyncMetadataSerializer(serializers.Serializer):
    """Nested ``sync_metadata`` — polling contract (+ optional integrity passthrough)."""

    content_hash = serializers.CharField(required=False, allow_blank=True)
    entity_versions = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
    )
    workflow_version = serializers.CharField(required=False, allow_blank=True)
    generated_at = serializers.CharField(required=False, allow_blank=True)
    last_action_log_id = serializers.CharField(required=False, allow_blank=True)
    workflow_integrity = serializers.DictField(required=False)
    compliance_integrity = serializers.DictField(required=False)
    drift_detected = serializers.BooleanField(required=False)
    job_detail_projection_version = serializers.CharField(
        required=False,
        allow_blank=True,
    )


class JobDetailResponseSerializer(serializers.Serializer):
    """
    Validates Job Detail ``data`` before envelope wrap.

    Skeleton: permissive dict fields until contract is finalized.
    """

    job = serializers.DictField(required=False, default=dict)
    workflow = serializers.DictField(required=False, default=dict)
    timeline = serializers.DictField(required=False, default=dict)
    pod_cod = serializers.DictField(required=False, default=dict)
    round_trip = serializers.DictField(required=False, default=dict)
    alerts = serializers.DictField(required=False, default=dict)
    sync_metadata = JobDetailSyncMetadataSerializer(required=False)
    next_action_hint = serializers.DictField(required=False)
