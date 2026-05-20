"""
mobile_api/serializers/driver_dashboard_activity.py

Lightweight timeline serializers for the driver dashboard activity feed.
"""
from __future__ import annotations

from rest_framework import serializers


class DashboardRecentActivityItemSerializer(serializers.Serializer):
    """
    Flat timeline row for mobile lists (no deep nesting).

    Legacy action-log fields remain optional for older clients.
    """

    activity_type = serializers.ChoiceField(
        choices=('action', 'shipment', 'movement', 'pod'),
    )
    occurred_at = serializers.CharField(allow_null=True, required=False)
    title = serializers.CharField(allow_blank=True)
    route_summary = serializers.CharField(allow_blank=True)
    action_code = serializers.CharField(allow_null=True, required=False)
    action_label = serializers.CharField(allow_null=True, required=False)
    shipment_id = serializers.UUIDField(allow_null=True, required=False)
    shipment_no = serializers.CharField(allow_null=True, required=False)
    movement_id = serializers.UUIDField(allow_null=True, required=False)
    movement_no = serializers.CharField(allow_null=True, required=False)
    pod_status = serializers.CharField(allow_null=True, required=False)
    document_id = serializers.UUIDField(allow_null=True, required=False)
    source = serializers.CharField(allow_blank=True)
    log_id = serializers.UUIDField(allow_null=True, required=False)
    log_no = serializers.CharField(allow_null=True, required=False)
    log_date = serializers.CharField(allow_null=True, required=False)


class DashboardRecentActivityFeedSerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=10)
    items = DashboardRecentActivityItemSerializer(many=True)
