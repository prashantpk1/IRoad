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
    shipment_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
    movement_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
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
        if lat is None or lon is None:
            raise serializers.ValidationError(
                str(_('mobile.issues.gps_required')),
                code='gps_required',
            )
        attrs['latitude'] = str(lat)
        attrs['longitude'] = str(lon)
        shipment_ref = str(attrs.get('shipment_id') or '').strip()
        movement_ref = str(attrs.get('movement_id') or '').strip()
        if not shipment_ref and not movement_ref:
            raise serializers.ValidationError(
                str(_('mobile.validation.failed')),
                code='job_reference_required',
            )
        attrs['shipment_id'] = shipment_ref
        attrs['movement_id'] = movement_ref
        return attrs
