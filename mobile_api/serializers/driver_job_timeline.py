"""
Timeline feed serializers for job detail execution history.
"""

from __future__ import annotations

from rest_framework import serializers


class TimelineGpsSerializer(serializers.Serializer):
    latitude = serializers.CharField(allow_blank=True)
    longitude = serializers.CharField(allow_blank=True)
    map_link = serializers.CharField(allow_blank=True, required=False)


class TimelineMediaPreviewSerializer(serializers.Serializer):
    media_id = serializers.UUIDField()
    line_no = serializers.IntegerField(min_value=1)
    media_type = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    captured_at = serializers.CharField(allow_null=True, required=False)
    preview_url = serializers.URLField(allow_null=True, required=False)
    has_file = serializers.BooleanField()


class TimelineStatusImpactsSerializer(serializers.Serializer):
    shipment = serializers.CharField(allow_null=True, required=False)
    movement = serializers.CharField(allow_null=True, required=False)
    booking = serializers.CharField(allow_null=True, required=False)


class TimelineEventsSerializer(serializers.Serializer):
    is_pod = serializers.BooleanField()
    is_cod = serializers.BooleanField()
    is_reversal = serializers.BooleanField()
    is_status_impact = serializers.BooleanField()


class TimelineItemSerializer(serializers.Serializer):
    log_id = serializers.UUIDField()
    log_no = serializers.CharField()
    action_name = serializers.CharField(allow_blank=True)
    action_code = serializers.CharField(allow_null=True, required=False)
    execution_time = serializers.CharField(allow_null=True, required=False)
    driver_name = serializers.CharField(allow_blank=True)
    gps = TimelineGpsSerializer()
    notes = serializers.CharField(allow_blank=True)
    media_previews = TimelineMediaPreviewSerializer(many=True)
    media_count = serializers.IntegerField(min_value=0)
    status_impacts = TimelineStatusImpactsSerializer()
    events = TimelineEventsSerializer()
    source = serializers.CharField(allow_blank=True, required=False)
    source_channel = serializers.CharField(allow_blank=True, required=False)
    shipment_id = serializers.UUIDField(required=False, allow_null=True)
    movement_id = serializers.UUIDField(required=False, allow_null=True)


class TimelinePaginationSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=('cursor',))
    page_size = serializers.IntegerField(min_value=1)
    count = serializers.IntegerField(min_value=0)
    has_next = serializers.BooleanField()
    next_cursor = serializers.CharField(allow_null=True, required=False)


class JobTimelineFeedSerializer(serializers.Serializer):
    job_type = serializers.ChoiceField(choices=('shipment', 'movement'))
    job_id = serializers.UUIDField()
    job_no = serializers.CharField()
    items = TimelineItemSerializer(many=True)
    pagination = TimelinePaginationSerializer()


class JobTimelineResponseDataSerializer(serializers.Serializer):
    timeline = JobTimelineFeedSerializer()
