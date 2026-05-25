"""
mobile_api/serializers/driver_job_detail.py

Flat Job Detail snapshot contract for shipment and movement execution screens.
"""

from __future__ import annotations

from rest_framework import serializers

from mobile_api.serializers.driver_job_list import (
    JobLatestActionSummarySerializer,
    JobOperationalIndicatorsSerializer,
    JobRouteProjectionSerializer,
    JobTruckSummarySerializer,
)
from mobile_api.serializers.driver_job_allowed_actions import (
    AllowedActionSerializer,
)


class AllowedActionsSummarySerializer(serializers.Serializer):
    context_label = serializers.CharField(allow_blank=True)
    count = serializers.IntegerField(min_value=0)
    actions = AllowedActionSerializer(many=True)
    primary_action = AllowedActionSerializer(required=False, allow_null=True)
    workflow_source = serializers.CharField(required=False, allow_blank=True)
    current_stage = serializers.CharField(required=False, allow_blank=True)


class JobDetailShipmentBlockSerializer(serializers.Serializer):
    shipment_id = serializers.UUIDField()
    shipment_no = serializers.CharField()
    shipment_status = serializers.CharField(allow_blank=True)
    booking_no = serializers.CharField(allow_null=True, required=False)
    order_type = serializers.CharField(allow_blank=True, required=False)
    sourcing_mode = serializers.CharField(allow_blank=True, required=False)
    shipment_date = serializers.CharField(allow_null=True, required=False)


class JobDetailMovementBlockSerializer(serializers.Serializer):
    movement_id = serializers.UUIDField()
    movement_no = serializers.CharField()
    status = serializers.CharField(allow_blank=True)
    movement_date = serializers.CharField(allow_null=True, required=False)
    movement_source = serializers.CharField(allow_blank=True, required=False)


class JobDetailStatusSerializer(serializers.Serializer):
    shipment_status = serializers.CharField(allow_null=True, required=False)
    movement_status = serializers.CharField(allow_null=True, required=False)
    operational_stage = serializers.CharField(allow_null=True, required=False)
    has_active_movement = serializers.BooleanField()


class DriftStateSerializer(serializers.Serializer):
    has_drift = serializers.BooleanField(required=False, default=False)
    has_status_drift = serializers.BooleanField(required=False, default=False)
    has_stage_drift = serializers.BooleanField(required=False, default=False)
    column_status = serializers.CharField(allow_null=True, required=False)
    authoritative_status = serializers.CharField(allow_null=True, required=False)
    latest_log_impact_status = serializers.CharField(allow_null=True, required=False)
    peak_log_impact_status = serializers.CharField(allow_null=True, required=False)
    reason = serializers.CharField(allow_null=True, required=False)
    recommended_column_status = serializers.CharField(allow_null=True, required=False)


class ExecutionStateSerializer(serializers.Serializer):
    shipment_status = serializers.CharField(allow_null=True, required=False)
    movement_status = serializers.CharField(allow_null=True, required=False)
    derived_status = serializers.CharField(allow_null=True, required=False)
    authoritative_status = serializers.CharField(allow_null=True, required=False)
    column_status = serializers.CharField(allow_null=True, required=False)
    execution_sub_stage = serializers.CharField(allow_null=True, required=False)
    operational_stage = serializers.CharField(allow_null=True, required=False)
    in_sync = serializers.BooleanField(required=False)
    has_drift = serializers.BooleanField(required=False)
    state_source = serializers.CharField(allow_blank=True, required=False)
    drift = DriftStateSerializer(required=False)


class CurrentWorkflowStateSerializer(serializers.Serializer):
    operational_stage = serializers.CharField(allow_null=True, required=False)
    shipment_status = serializers.CharField(allow_null=True, required=False)
    movement_status = serializers.CharField(allow_null=True, required=False)
    has_active_movement = serializers.BooleanField(required=False)
    derived_status = serializers.CharField(allow_null=True, required=False)
    status_in_sync = serializers.BooleanField()
    allowed_actions_count = serializers.IntegerField(min_value=0)
    needs_pod = serializers.BooleanField()
    needs_cod = serializers.BooleanField()
    is_active = serializers.BooleanField()
    is_empty_move = serializers.BooleanField()
    job_type = serializers.ChoiceField(choices=('shipment', 'movement'))


class PodStateSerializer(serializers.Serializer):
    status = serializers.CharField(allow_blank=True)
    is_pending = serializers.BooleanField()
    needs_attention = serializers.BooleanField()
    pod_type = serializers.CharField(allow_blank=True, required=False)


class CodStateSerializer(serializers.Serializer):
    order_type = serializers.CharField(allow_blank=True)
    cod_amount = serializers.CharField(allow_blank=True)
    collection_status = serializers.CharField(allow_blank=True)
    is_cod_order = serializers.BooleanField()
    is_collection_pending = serializers.BooleanField()


class DriverContextSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField(required=False, allow_null=True)
    driver_code = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    english_name = serializers.CharField(allow_blank=True, required=False)
    arabic_name = serializers.CharField(allow_blank=True, required=False)
    tenant_user_id = serializers.UUIDField(required=False, allow_null=True)


class TimelinePreviewItemSerializer(serializers.Serializer):
    log_id = serializers.UUIDField()
    log_no = serializers.CharField()
    log_date = serializers.CharField(allow_null=True, required=False)
    action_code = serializers.CharField(allow_null=True, required=False)
    action_label = serializers.CharField(allow_null=True, required=False)
    source = serializers.CharField(allow_blank=True, required=False)
    source_channel = serializers.CharField(allow_blank=True, required=False)
    notes = serializers.CharField(allow_blank=True, required=False)
    shipment_id = serializers.UUIDField(required=False, allow_null=True)
    movement_id = serializers.UUIDField(required=False, allow_null=True)
    status_impact = serializers.CharField(allow_null=True, required=False)
    latitude = serializers.CharField(allow_blank=True, required=False)
    longitude = serializers.CharField(allow_blank=True, required=False)
    is_reversal = serializers.BooleanField(required=False, default=False)


class JobSummarySerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    job_type = serializers.ChoiceField(choices=('shipment', 'movement'))
    job_no = serializers.CharField()
    current_status = serializers.CharField(allow_blank=True)
    route_summary = serializers.CharField(allow_blank=True)
    from_location = serializers.CharField(allow_blank=True)
    to_location = serializers.CharField(allow_blank=True)
    next_action_hint = serializers.CharField(allow_null=True, required=False)
    shipment_id = serializers.UUIDField(required=False, allow_null=True)
    shipment_no = serializers.CharField(required=False, allow_blank=True)
    booking_no = serializers.CharField(required=False, allow_null=True)
    order_type = serializers.CharField(required=False, allow_blank=True)
    shipment_date = serializers.CharField(required=False, allow_null=True)
    movement_id = serializers.UUIDField(required=False, allow_null=True)
    movement_no = serializers.CharField(required=False, allow_blank=True)
    movement_source = serializers.CharField(required=False, allow_blank=True)
    empty_move_reason = serializers.CharField(required=False, allow_blank=True)
    movement_date = serializers.CharField(required=False, allow_null=True)
    linked_movement_id = serializers.UUIDField(required=False, allow_null=True)
    linked_movement_no = serializers.CharField(required=False, allow_blank=True)
    linked_shipment_id = serializers.UUIDField(required=False, allow_null=True)
    linked_shipment_no = serializers.CharField(required=False, allow_blank=True)


class JobDetailSnapshotSerializer(serializers.Serializer):
    """Unified job detail envelope (shipment + movement endpoints)."""

    job_summary = JobSummarySerializer()
    job_type = serializers.ChoiceField(choices=('shipment', 'movement'))
    job_id = serializers.UUIDField()
    job_no = serializers.CharField()
    execution_stage = serializers.CharField(allow_blank=True)
    current_workflow_state = CurrentWorkflowStateSerializer()
    shipment = JobDetailShipmentBlockSerializer(required=False, allow_null=True)
    movement = JobDetailMovementBlockSerializer(required=False, allow_null=True)
    status = JobDetailStatusSerializer()
    execution_state = ExecutionStateSerializer()
    route = JobRouteProjectionSerializer()
    route_summary = serializers.CharField(allow_blank=True)
    from_location = serializers.CharField(allow_blank=True)
    to_location = serializers.CharField(allow_blank=True)
    truck = JobTruckSummarySerializer(required=False, allow_null=True)
    truck_summary = JobTruckSummarySerializer(required=False, allow_null=True)
    driver_context = DriverContextSerializer()
    pod = PodStateSerializer(required=False, allow_null=True)
    cod = CodStateSerializer(required=False, allow_null=True)
    pod_status = serializers.CharField(allow_blank=True, required=False)
    cod_status = serializers.CharField(allow_blank=True, required=False)
    collection_status = serializers.CharField(allow_blank=True, required=False)
    latest_action = JobLatestActionSummarySerializer(required=False, allow_null=True)
    timeline_preview = TimelinePreviewItemSerializer(many=True)
    allowed_actions_summary = AllowedActionsSummarySerializer()
    operational_indicators = JobOperationalIndicatorsSerializer()
    next_action_hint = serializers.CharField(allow_null=True, required=False)
    updated_at = serializers.CharField(allow_null=True, required=False)


class JobDetailMetaSerializer(serializers.Serializer):
    entity_type = serializers.ChoiceField(choices=('shipment', 'movement'))
    include_timeline = serializers.BooleanField()
    include_actions = serializers.BooleanField()
    timeline_preview_limit = serializers.IntegerField(min_value=1, max_value=50)


class ShipmentJobDetailDataSerializer(serializers.Serializer):
    snapshot = JobDetailSnapshotSerializer()


class MovementJobDetailDataSerializer(serializers.Serializer):
    snapshot = JobDetailSnapshotSerializer()
