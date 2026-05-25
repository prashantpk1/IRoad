"""
Allowed-actions contract — engine-driven membership + action metadata projections.
"""

from __future__ import annotations

from rest_framework import serializers


class ExecutionRequirementsSerializer(serializers.Serializer):
    gps = serializers.BooleanField()
    photo = serializers.BooleanField()
    photo_min_count = serializers.IntegerField(min_value=0)
    video = serializers.BooleanField()
    video_min_count = serializers.IntegerField(min_value=0)
    note = serializers.BooleanField()
    note_required = serializers.BooleanField()
    signature = serializers.BooleanField(required=False)
    auto_movement_post = serializers.BooleanField(required=False)
    auto_pod_post = serializers.BooleanField(required=False)
    auto_shipment_post = serializers.BooleanField(required=False)
    hard_copy_collection = serializers.BooleanField(required=False)
    shipment_status_impact = serializers.CharField(allow_blank=True, required=False)
    movement_status_impact = serializers.CharField(allow_blank=True, required=False)


class AllowedActionSerializer(serializers.Serializer):
    action_id = serializers.UUIDField()
    action_code = serializers.CharField()
    action_name = serializers.CharField()
    execution_label = serializers.CharField()
    requires_gps = serializers.BooleanField()
    requires_photo = serializers.BooleanField()
    requires_video = serializers.BooleanField()
    requires_note = serializers.BooleanField()
    action_category = serializers.CharField(allow_blank=True)
    execution_order = serializers.IntegerField(min_value=0)
    sort_index = serializers.IntegerField(min_value=0, required=False)
    current_stage = serializers.CharField(allow_blank=True)
    execution_requirements = ExecutionRequirementsSerializer()


class DriftStateSerializer(serializers.Serializer):
    has_drift = serializers.BooleanField(required=False, default=False)
    column_status = serializers.CharField(allow_null=True, required=False)
    authoritative_status = serializers.CharField(allow_null=True, required=False)
    reason = serializers.CharField(allow_null=True, required=False)


class ExecutionStateSerializer(serializers.Serializer):
    shipment_status = serializers.CharField(allow_null=True, required=False)
    movement_status = serializers.CharField(allow_null=True, required=False)
    derived_status = serializers.CharField(allow_null=True, required=False)
    authoritative_status = serializers.CharField(allow_null=True, required=False)
    execution_sub_stage = serializers.CharField(allow_null=True, required=False)
    operational_stage = serializers.CharField(allow_null=True, required=False)
    in_sync = serializers.BooleanField(required=False)
    has_drift = serializers.BooleanField(required=False)
    state_source = serializers.CharField(allow_blank=True, required=False)
    drift = DriftStateSerializer(required=False)


class AllowedActionsPayloadSerializer(serializers.Serializer):
    job_type = serializers.ChoiceField(choices=('shipment', 'movement'))
    job_id = serializers.UUIDField()
    job_no = serializers.CharField()
    current_stage = serializers.CharField(allow_blank=True)
    context_label = serializers.CharField(allow_blank=True)
    count = serializers.IntegerField(min_value=0)
    actions = AllowedActionSerializer(many=True)
    primary_action = AllowedActionSerializer(required=False, allow_null=True)
    workflow_source = serializers.CharField()
    execution_state = ExecutionStateSerializer(required=False)


class AllowedActionsResponseDataSerializer(serializers.Serializer):
    allowed_actions = AllowedActionsPayloadSerializer()
