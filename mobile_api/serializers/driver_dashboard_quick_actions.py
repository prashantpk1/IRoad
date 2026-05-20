"""
mobile_api/serializers/driver_dashboard_quick_actions.py

Read-only serializers for dashboard shortcut metadata.
"""
from __future__ import annotations

from rest_framework import serializers


class QuickActionExecutionSerializer(serializers.Serializer):
    phase = serializers.ChoiceField(choices=('placeholder', 'route_hint'))
    route_key = serializers.CharField()
    deep_link = serializers.CharField(allow_blank=True)
    api_path = serializers.CharField(allow_null=True, required=False)
    http_method = serializers.CharField(allow_null=True, required=False)


class DashboardQuickActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()
    sort_order = serializers.IntegerField(min_value=0)
    visible = serializers.BooleanField()
    enabled = serializers.BooleanField()
    reason_code = serializers.CharField(allow_null=True, required=False)
    reason_message = serializers.CharField(allow_null=True, required=False)
    required_capabilities = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )
    execution = QuickActionExecutionSerializer()
    shipment_id = serializers.UUIDField(allow_null=True, required=False)
    movement_id = serializers.UUIDField(allow_null=True, required=False)
