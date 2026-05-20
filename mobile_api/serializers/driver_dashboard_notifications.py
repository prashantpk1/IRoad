"""
mobile_api/serializers/driver_dashboard_notifications.py

Read-only serializers for driver dashboard notification summary (Phase 1).
"""
from __future__ import annotations

from rest_framework import serializers


class DashboardNotificationFcmSerializer(serializers.Serializer):
    """FCM readiness metadata (registration only — no send)."""

    push_enabled = serializers.BooleanField()
    device_token_registered = serializers.BooleanField()
    channel = serializers.CharField()
    inbox_deep_link = serializers.CharField()
    register_token_route = serializers.CharField()


class DashboardNotificationItemSerializer(serializers.Serializer):
    """Lightweight alert projection (inbox, push receipt, or ephemeral)."""

    id = serializers.CharField()
    category = serializers.CharField()
    severity = serializers.CharField()
    source = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True, required=False)
    is_read = serializers.BooleanField()
    event_code = serializers.CharField(allow_null=True, required=False)
    shipment_id = serializers.CharField(allow_null=True, required=False)
    movement_id = serializers.CharField(allow_null=True, required=False)
    created_at = serializers.CharField(allow_null=True, required=False)
    deep_link = serializers.CharField(required=False)
    ephemeral = serializers.BooleanField(required=False, default=False)
    push_receipt = serializers.BooleanField(required=False, default=False)
    push_receipt_id = serializers.CharField(allow_null=True, required=False)


class DashboardNotificationsSummarySerializer(serializers.Serializer):
    unread_count = serializers.IntegerField(min_value=0)
    push_recent_count = serializers.IntegerField(min_value=0, required=False)
    ephemeral_hint_count = serializers.IntegerField(min_value=0, required=False)
    critical_count = serializers.IntegerField(min_value=0)
    assignment_count = serializers.IntegerField(min_value=0)
    operational_warnings_count = serializers.IntegerField(min_value=0)
    items = DashboardNotificationItemSerializer(many=True)
    fcm = DashboardNotificationFcmSerializer()
