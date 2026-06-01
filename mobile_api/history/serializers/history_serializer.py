"""
mobile_api/history/serializers/history_serializer.py

DRF validation shell for History API ``data`` payloads.
"""
from __future__ import annotations

from rest_framework import serializers


class HistoryListResponseSerializer(serializers.Serializer):
    """GET /driver/history/ list envelope."""

    items = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    count = serializers.IntegerField(required=False, default=0)
    results_found = serializers.IntegerField(required=False, default=0)
    total_records = serializers.IntegerField(required=False, default=0)
    total_pages = serializers.IntegerField(required=False, default=0)
    current_page = serializers.IntegerField(required=False, default=1)
    page_size = serializers.IntegerField(required=False, default=10)


class HistoryDetailResponseSerializer(serializers.Serializer):
    """GET /driver/history/<shipment_id>/ detail envelope."""

    trip_type = serializers.CharField(required=False, allow_blank=True, default='')
    pickup_address = serializers.DictField(required=False, default=dict)
    drop_address = serializers.DictField(required=False, default=dict)
    summary = serializers.DictField(required=False, default=dict)
    workflow_status = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )
    timeline = serializers.DictField(required=False, default=dict)
    actions_fired_count = serializers.IntegerField(required=False, default=0)
    history_projection_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default='1',
    )
