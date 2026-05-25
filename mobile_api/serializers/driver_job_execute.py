"""
Execute-action request/response contracts for mobile job execution.
"""

from __future__ import annotations

from rest_framework import serializers

from mobile_api.serializers.driver_job_allowed_actions import (
    AllowedActionsPayloadSerializer,
    ExecutionStateSerializer,
)
from mobile_api.serializers.driver_job_list import JobLatestActionSummarySerializer


class ActionLogMediaItemSerializer(serializers.Serializer):
    media_type = serializers.CharField(required=False, allow_blank=True, max_length=16)
    description = serializers.CharField(required=False, allow_blank=True, max_length=255)
    captured_at = serializers.CharField(required=False, allow_blank=True)


class ExecuteDriverActionSerializer(serializers.Serializer):
    action_id = serializers.UUIDField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=128)
    source_ref = serializers.CharField(required=False, allow_blank=True, max_length=128)
    notes = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.CharField(required=False, allow_blank=True, max_length=32)
    longitude = serializers.CharField(required=False, allow_blank=True, max_length=32)
    map_link = serializers.URLField(required=False, allow_blank=True, max_length=500)
    log_date = serializers.DateTimeField(required=False, allow_null=True)
    cod_amount = serializers.DecimalField(
        required=False,
        allow_null=True,
        max_digits=12,
        decimal_places=2,
    )
    media = ActionLogMediaItemSerializer(many=True, required=False)


class ActionExecutionResultSerializer(serializers.Serializer):
    log_id = serializers.UUIDField()
    log_no = serializers.CharField()
    log_date = serializers.CharField(allow_null=True, required=False)
    action_code = serializers.CharField(allow_null=True, required=False)
    action_label = serializers.CharField(allow_null=True, required=False)
    reused_existing = serializers.BooleanField()
    source_channel = serializers.CharField()
    media_saved_count = serializers.IntegerField(min_value=0)


class WorkflowRefreshSerializer(serializers.Serializer):
    allowed_actions = AllowedActionsPayloadSerializer()
    execution_state = ExecutionStateSerializer()
    latest_action = JobLatestActionSummarySerializer(allow_null=True)
    shipment_status = serializers.CharField(allow_null=True, required=False)
    movement_status = serializers.CharField(allow_null=True, required=False)
    operational_stage = serializers.CharField(allow_blank=True)


class ExecuteActionResponseDataSerializer(serializers.Serializer):
    execution = ActionExecutionResultSerializer()
    workflow = WorkflowRefreshSerializer()
