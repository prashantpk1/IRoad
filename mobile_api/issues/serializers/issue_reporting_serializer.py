"""
mobile_api/issues/serializers/issue_reporting_serializer.py
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_ITEMS
from mobile_api.issues.models.operational_issue import OperationalIssue


class IssueMediaItemSerializer(serializers.Serializer):
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


class IssueReportingRequestSerializer(serializers.Serializer):
    client_issue_id = serializers.CharField(max_length=128)
    shipment_id = serializers.CharField(max_length=64)
    issue_type = serializers.ChoiceField(
        choices=[c.value for c in OperationalIssue.IssueType],
    )
    severity = serializers.ChoiceField(
        choices=[c.value for c in OperationalIssue.Severity],
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    media = IssueMediaItemSerializer(many=True, required=False, default=list)

    def validate_client_issue_id(self, value: str) -> str:
        token = (value or '').strip()
        if not token:
            raise serializers.ValidationError(
                str(_('mobile.issues.client_issue_id_required')),
                code='client_issue_id_required',
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
        return attrs
