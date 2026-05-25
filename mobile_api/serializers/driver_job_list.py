"""
mobile_api/serializers/driver_job_list.py

Mobile-safe job list contracts — flat primary fields, optional compact nests.
"""
from __future__ import annotations

from rest_framework import serializers


class JobLatestActionSummarySerializer(serializers.Serializer):
    log_id = serializers.UUIDField(required=False, allow_null=True)
    log_no = serializers.CharField(required=False, allow_blank=True)
    action_code = serializers.CharField(required=False, allow_null=True)
    action_label = serializers.CharField(required=False, allow_null=True)
    log_date = serializers.CharField(required=False, allow_null=True)


class JobRouteProjectionSerializer(serializers.Serializer):
    summary = serializers.CharField(allow_blank=True)
    from_label = serializers.CharField(allow_blank=True)
    to_label = serializers.CharField(allow_blank=True)


class JobTruckSummarySerializer(serializers.Serializer):
    truck_id = serializers.UUIDField(required=False, allow_null=True)
    truck_code = serializers.CharField(required=False, allow_blank=True)
    plate_number = serializers.CharField(required=False, allow_blank=True)
    truck_status = serializers.CharField(required=False, allow_null=True)
    sourcing_mode = serializers.CharField(required=False, allow_null=True)


class JobOperationalIndicatorsSerializer(serializers.Serializer):
    needs_pod = serializers.BooleanField()
    needs_cod = serializers.BooleanField()
    is_active = serializers.BooleanField()
    is_empty_move = serializers.BooleanField()


class JobCardSerializer(serializers.Serializer):
    """
    Unified job card envelope for shipment and movement list items.

    Mobile clients should prefer top-level ``route_summary``, ``truck_*``, and
    indicator booleans; nested blocks are stable mirrors only.
    """

    job_id = serializers.UUIDField()
    job_type = serializers.ChoiceField(choices=('shipment', 'movement'))
    job_no = serializers.CharField()
    current_status = serializers.CharField(allow_blank=True)

    route_summary = serializers.CharField(allow_blank=True)
    from_location = serializers.CharField(allow_blank=True)
    to_location = serializers.CharField(allow_blank=True)

    truck_id = serializers.UUIDField(required=False, allow_null=True)
    truck_code = serializers.CharField(required=False, allow_blank=True)
    plate_number = serializers.CharField(required=False, allow_blank=True)
    truck_status = serializers.CharField(required=False, allow_null=True)
    truck_sourcing_mode = serializers.CharField(required=False, allow_blank=True)

    latest_action_summary = JobLatestActionSummarySerializer(
        required=False,
        allow_null=True,
    )
    next_action_hint = serializers.CharField(required=False, allow_null=True)

    pod_status = serializers.CharField(required=False, allow_blank=True)
    cod_status = serializers.CharField(required=False, allow_blank=True)
    collection_status = serializers.CharField(required=False, allow_blank=True)

    needs_pod = serializers.BooleanField()
    needs_cod = serializers.BooleanField()
    is_active = serializers.BooleanField()
    is_empty_move = serializers.BooleanField()
    is_pod_pending = serializers.BooleanField(required=False)
    is_cod_pending = serializers.BooleanField(required=False)
    is_cod_order = serializers.BooleanField(required=False)

    updated_at = serializers.CharField(allow_null=True, required=False)
    created_at = serializers.CharField(allow_null=True, required=False)

    route = JobRouteProjectionSerializer(required=False)
    truck = JobTruckSummarySerializer(required=False, allow_null=True)
    indicators = JobOperationalIndicatorsSerializer(required=False)
    priority = JobOperationalIndicatorsSerializer(required=False)


class ShipmentJobCardSerializer(JobCardSerializer):
    shipment_id = serializers.UUIDField()
    shipment_no = serializers.CharField()
    movement_id = serializers.UUIDField(required=False, allow_null=True)
    movement_no = serializers.CharField(required=False, allow_null=True, default='')
    booking_no = serializers.CharField(allow_null=True, required=False)
    order_type = serializers.CharField(allow_blank=True, required=False)
    shipment_date = serializers.CharField(allow_null=True, required=False)


class MovementJobCardSerializer(JobCardSerializer):
    movement_id = serializers.UUIDField()
    movement_no = serializers.CharField()
    shipment_id = serializers.UUIDField(required=False, allow_null=True)
    shipment_no = serializers.CharField(required=False, allow_null=True, default='')
    movement_source = serializers.CharField(allow_blank=True, required=False)
    empty_move_reason = serializers.CharField(allow_blank=True, required=False)
    movement_date = serializers.CharField(allow_null=True, required=False)


class MovementJobListMetaSerializer(serializers.Serializer):
    tab = serializers.CharField()
    queue = serializers.CharField()
    sort = serializers.CharField()
    entity_type = serializers.CharField()
    tab_locked = serializers.BooleanField(required=False, default=False)
    queue_locked = serializers.BooleanField(required=False, default=False)
    search = serializers.CharField(required=False, allow_blank=True, default='')
    date_from = serializers.CharField(required=False, allow_blank=True, default='')
    date_to = serializers.CharField(required=False, allow_blank=True, default='')
    date_field = serializers.ChoiceField(
        choices=('updated', 'operational'),
        required=False,
        default='updated',
    )
    include_actions = serializers.BooleanField(required=False, default=True)


class ShipmentJobListMetaSerializer(MovementJobListMetaSerializer):
    """Shipment list pagination meta (same shape as movement)."""
    pass


class JobSummaryCountersSerializer(serializers.Serializer):
    """My Jobs summary badges — aligned with list tab/queue routes."""

    active_shipments = serializers.IntegerField(min_value=0)
    completed_shipments = serializers.IntegerField(min_value=0)
    cancelled_shipments = serializers.IntegerField(min_value=0)
    active_movements = serializers.IntegerField(min_value=0)
    completed_movements = serializers.IntegerField(min_value=0)
    cancelled_movements = serializers.IntegerField(min_value=0)
    pod_pending = serializers.IntegerField(min_value=0)
    cod_pending = serializers.IntegerField(min_value=0)


class JobListMetaSerializer(serializers.Serializer):
    tab = serializers.CharField()
    queue = serializers.CharField()
    sort = serializers.CharField()
    entity_type = serializers.CharField()


class JobListPaginatedDataSerializer(serializers.Serializer):
    items = JobCardSerializer(many=True)
    meta = JobListMetaSerializer()
    total_records = serializers.IntegerField(required=False)
    total_pages = serializers.IntegerField(required=False)
    current_page = serializers.IntegerField(required=False)
    page_size = serializers.IntegerField(required=False)


class ShipmentJobListPaginatedDataSerializer(serializers.Serializer):
    items = ShipmentJobCardSerializer(many=True)
    meta = ShipmentJobListMetaSerializer()
    total_records = serializers.IntegerField(required=False)
    total_pages = serializers.IntegerField(required=False)
    current_page = serializers.IntegerField(required=False)
    page_size = serializers.IntegerField(required=False)


class MovementJobListPaginatedDataSerializer(serializers.Serializer):
    items = MovementJobCardSerializer(many=True)
    meta = MovementJobListMetaSerializer()
    total_records = serializers.IntegerField(required=False)
    total_pages = serializers.IntegerField(required=False)
    current_page = serializers.IntegerField(required=False)
    page_size = serializers.IntegerField(required=False)


class JobSummarySerializer(serializers.Serializer):
    counters = JobSummaryCountersSerializer()
    entity_types = serializers.ListField(child=serializers.CharField())
