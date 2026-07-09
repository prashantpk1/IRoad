"""
mobile_api/execution/serializers/execute_action_serializer.py

DRF request/response validation for the Unified Execute Action API.
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_ITEMS


class ExecuteActionMediaItemSerializer(serializers.Serializer):
    """One evidence attachment for ``TenantOperationActionMedia``."""

    media_type = serializers.ChoiceField(
        choices=['photo', 'video', 'document', 'signature'],
        required=False,
        allow_blank=True,
    )
    file_ref = serializers.CharField(required=False, allow_blank=True, max_length=500)
    file_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    media_id = serializers.CharField(required=False, allow_blank=True)
    sort_order = serializers.IntegerField(required=False, default=0)


class ExecuteActionRequestSerializer(serializers.Serializer):
    """
    POST body for unified execute.

    Canonical contract::

        client_action_id, workflow_version, content_hash,
        latitude, longitude, notes, media
    """

    client_action_id = serializers.CharField(max_length=128)
    workflow_version = serializers.CharField(max_length=256)
    content_hash = serializers.CharField(max_length=128)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    media = ExecuteActionMediaItemSerializer(many=True, required=False, default=list)
    custody_submission_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text='Hard POD custody submission to promote when executing A7H.',
    )
    client_submission_id = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        help_text='Client idempotency key from POST /hard-pod/submit/ (A7H fallback).',
    )
    capture_bundle_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        help_text='Staged POD capture bundle to promote after Action Log insert.',
    )
    pod_capture_bundle_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
    )
    bundle_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
    )

    # Optional extensions (orchestrator / kernel)
    map_link = serializers.CharField(required=False, allow_blank=True, default='')
    location_address = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text='Reverse-geocoded address for empty-move route endpoints.',
    )
    mobile_cod_amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    entity_versions = serializers.DictField(
        child=serializers.CharField(allow_blank=True),
        required=False,
    )

    def validate_client_action_id(self, value: str) -> str:
        token = (value or '').strip()
        if not token:
            raise serializers.ValidationError(
                str(_('mobile.jobs.execute.idempotency_key_required')),
                code='idempotency_key_required',
            )
        return token

    def validate_media(self, value: list) -> list:
        if value and len(value) > EXECUTION_MEDIA_MAX_ITEMS:
            raise serializers.ValidationError(
                str(_('mobile.jobs.execute.media_limit_exceeded')),
                code='media_limit_exceeded',
            )
        return value

    def validate(self, attrs: dict) -> dict:
        lat = attrs.get('latitude')
        lon = attrs.get('longitude')
        if lat is not None:
            attrs['latitude'] = str(lat)
        if lon is not None:
            attrs['longitude'] = str(lon)
        bundle = (
            (attrs.get('capture_bundle_id') or '')
            or (attrs.get('pod_capture_bundle_id') or '')
            or (attrs.get('bundle_id') or '')
        ).strip()
        if bundle:
            attrs['capture_bundle_id'] = bundle
        return attrs


class ExecuteActionExecutionSerializer(serializers.Serializer):
    """Nested ``execution`` slice."""

    job_type = serializers.CharField()
    job_id = serializers.CharField()
    action_code = serializers.CharField()
    reused_existing = serializers.BooleanField(required=False, default=False)
    idempotent_replay = serializers.BooleanField(required=False, default=False)
    replayed = serializers.BooleanField(required=False, default=False)
    original_action_log_id = serializers.CharField(required=False, allow_null=True)
    executed_at = serializers.CharField(required=False, allow_null=True)
    action_log_id = serializers.CharField(required=False, allow_null=True)
    log_no = serializers.CharField(required=False, allow_blank=True)
    log_date = serializers.CharField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True)
    job_closed = serializers.BooleanField(required=False, default=False)
    next_step = serializers.CharField(required=False, allow_blank=True, default='')


class ExecuteActionTimelinePreviewSerializer(serializers.Serializer):
    """Timeline preview bundle (Job Detail timeline projection subset)."""

    scope = serializers.CharField(required=False, allow_blank=True)
    timeline_preview = serializers.ListField(child=serializers.DictField(), required=False)
    timeline_cursor = serializers.CharField(required=False, allow_blank=True)
    has_more = serializers.BooleanField(required=False, default=False)


class ExecuteActionResponseSerializer(serializers.Serializer):
    """Top-level ``data`` envelope for execute response."""

    execution = ExecuteActionExecutionSerializer()
    workflow = serializers.DictField()
    pod_cod = serializers.DictField(required=False)
    timeline_preview = serializers.DictField(required=False)
    sync_metadata = serializers.DictField()
    alerts = serializers.DictField(required=False)
    next_action_hint = serializers.DictField(required=False)
