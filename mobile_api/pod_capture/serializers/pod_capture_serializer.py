"""
mobile_api/pod_capture/serializers/pod_capture_serializer.py

DRF request/response validation for POD Capture API.
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from mobile_api.execution.evidence.constants import (
    EXECUTION_MEDIA_MAX_ITEMS,
    POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS,
)
from mobile_api.execution.evidence.video_duration_validation import (
    video_duration_exceeded_message,
)


class PodCaptureMediaItemSerializer(serializers.Serializer):
    media_type = serializers.ChoiceField(
        choices=['photo', 'video', 'document', 'signature'],
        required=False,
        allow_blank=True,
    )
    file_ref = serializers.CharField(required=False, allow_blank=True, max_length=500)
    file_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    checksum = serializers.CharField(required=False, allow_blank=True, max_length=128)
    sort_order = serializers.IntegerField(required=False, default=0)
    duration_seconds = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0,
        help_text='Video clip length in seconds (max 60 for POD capture).',
    )

    def validate(self, attrs: dict) -> dict:
        duration = attrs.get('duration_seconds')
        media_type = (attrs.get('media_type') or '').strip().casefold()
        if duration is not None and media_type in {'video', ''}:
            if float(duration) > float(POD_CAPTURE_VIDEO_MAX_DURATION_SECONDS):
                raise serializers.ValidationError(
                    {
                        'duration_seconds': video_duration_exceeded_message(),
                    }
                )
        return attrs


class PodCaptureRequestSerializer(serializers.Serializer):
    """
    POST body for ``POST .../jobs/shipments/<shipment_id>/pod/capture/``.

    ``client_capture_id`` provides offline idempotency for staged bundles.
    ``target_action_code`` is optional — resolved from Action Master when omitted.
    """

    client_capture_id = serializers.CharField(max_length=128)
    content_hash = serializers.CharField(max_length=128)
    workflow_version = serializers.CharField(max_length=256)
    pod_type = serializers.ChoiceField(
        choices=['digital', 'soft', 'hard', 'signature', 'multi_page', 'video'],
        required=False,
        allow_blank=True,
    )
    pod_capture_type = serializers.ChoiceField(
        choices=['digital', 'soft', 'hard', 'signature', 'multi_page', 'video'],
        required=False,
        allow_blank=True,
        help_text='Deprecated alias for ``pod_type``.',
    )
    target_action_code = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text='Action Master code for the POD step; inferred when omitted.',
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    media = PodCaptureMediaItemSerializer(many=True)
    entity_versions = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
    )

    def validate(self, attrs: dict) -> dict:
        pod_type = (attrs.get('pod_type') or attrs.get('pod_capture_type') or '').strip()
        if pod_type:
            attrs['pod_type'] = pod_type
            attrs['pod_capture_type'] = pod_type
        return attrs

    def validate_client_capture_id(self, value: str) -> str:
        token = (value or '').strip()
        if not token:
            raise serializers.ValidationError(
                str(_('mobile.pod_capture.client_capture_id_required')),
                code='client_capture_id_required',
            )
        return token

    def validate_media(self, value: list) -> list:
        if not value:
            raise serializers.ValidationError(
                str(_('mobile.pod_capture.media_required')),
                code='media_required',
            )
        if len(value) > EXECUTION_MEDIA_MAX_ITEMS:
            raise serializers.ValidationError(
                str(_('mobile.pod_capture.media_limit_exceeded')),
                code='media_limit_exceeded',
            )
        return value


class PodCaptureResponseSerializer(serializers.Serializer):
    """Response ``data`` envelope (orchestrator-built dict)."""

    capture_bundle = serializers.DictField()
    compliance = serializers.DictField()
    sync_metadata = serializers.DictField(required=False)
    next_step = serializers.DictField()
