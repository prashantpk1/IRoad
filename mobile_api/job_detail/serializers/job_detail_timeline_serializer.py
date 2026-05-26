"""
mobile_api/job_detail/serializers/job_detail_timeline_serializer.py

DRF validation for paginated Job Detail timeline responses.
"""
from __future__ import annotations

from rest_framework import serializers


class JobDetailTimelineEventSerializer(serializers.Serializer):
    """One Action Log–derived timeline event."""

    log_id = serializers.CharField()
    event_type = serializers.CharField(required=False, allow_blank=True)
    authority = serializers.CharField(required=False, allow_blank=True)


class JobDetailTimelinePageSerializer(serializers.Serializer):
    """Paginated timeline page contract."""

    events = serializers.ListField(child=serializers.DictField(), required=False)
    next_cursor = serializers.CharField(required=False, allow_blank=True)
    has_more = serializers.BooleanField(required=False, default=False)
