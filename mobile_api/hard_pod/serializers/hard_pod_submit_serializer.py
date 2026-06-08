"""
mobile_api/hard_pod/serializers/hard_pod_submit_serializer.py

POST body validation for Hard POD custody submit.
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_ITEMS


class HardPodConfirmedPageSerializer(serializers.Serializer):
    page_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    document_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    line_no = serializers.IntegerField(required=False, min_value=1)
    confirmed = serializers.BooleanField(required=False, default=True)


class HardPodSubmitMediaItemSerializer(serializers.Serializer):
    media_type = serializers.ChoiceField(
        choices=['photo', 'video', 'document', 'signature'],
        required=False,
        allow_blank=True,
    )
    file_ref = serializers.CharField(required=False, allow_blank=True, max_length=500)
    file_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    mime_type = serializers.CharField(required=False, allow_blank=True, max_length=128)
    checksum = serializers.CharField(required=False, allow_blank=True, max_length=128)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    sort_order = serializers.IntegerField(required=False, default=0)


class HardPodSubmitRequestSerializer(serializers.Serializer):
    client_submission_id = serializers.CharField(max_length=128)
    shipment_id = serializers.CharField(max_length=64)
    receiver_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    receiver_contact = serializers.CharField(required=False, allow_blank=True, max_length=128)
    handoff_notes = serializers.CharField(required=False, allow_blank=True, default='')
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    media = HardPodSubmitMediaItemSerializer(many=True, required=False, default=list)
    confirmed_pages = HardPodConfirmedPageSerializer(many=True, required=True)

    def validate_client_submission_id(self, value: str) -> str:
        token = (value or '').strip()
        if not token:
            raise serializers.ValidationError(
                str(_('mobile.hard_pod.client_submission_id_required')),
                code='client_submission_id_required',
            )
        return token

    def validate_shipment_id(self, value: str) -> str:
        token = (value or '').strip()
        if not token:
            raise serializers.ValidationError(
                str(_('mobile.validation.failed')),
                code='invalid_shipment_reference',
            )
        return token

    def validate_media(self, value: list) -> list:
        if len(value or []) > EXECUTION_MEDIA_MAX_ITEMS:
            raise serializers.ValidationError(
                str(_('mobile.jobs.execute.media_limit_exceeded')),
                code='media_limit_exceeded',
            )
        return value or []
