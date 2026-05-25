"""
POD upload and COD collection request/response contracts.
"""

from __future__ import annotations

from rest_framework import serializers

from mobile_api.serializers.driver_job_execute import (
    ActionExecutionResultSerializer,
    WorkflowRefreshSerializer,
)


class UploadPodRequestSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=128)
    source_ref = serializers.CharField(required=False, allow_blank=True, max_length=128)
    notes = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.CharField(required=False, allow_blank=True, max_length=32)
    longitude = serializers.CharField(required=False, allow_blank=True, max_length=32)
    map_link = serializers.URLField(required=False, allow_blank=True, max_length=500)
    log_date = serializers.DateTimeField(required=False, allow_null=True)


class CollectCodRequestSerializer(serializers.Serializer):
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


class PodDocumentSummarySerializer(serializers.Serializer):
    document_id = serializers.UUIDField()
    record_no = serializers.CharField()
    status = serializers.CharField(allow_blank=True)
    document_type = serializers.CharField(allow_blank=True)


class PodComplianceSerializer(serializers.Serializer):
    pod_status = serializers.CharField(allow_blank=True)
    pod_type = serializers.CharField(allow_blank=True)
    needs_attention = serializers.BooleanField()
    is_pending = serializers.BooleanField()
    shipment_status = serializers.CharField(allow_blank=True)
    document = PodDocumentSummarySerializer(required=False, allow_null=True)


class TreasuryPostingSerializer(serializers.Serializer):
    posted = serializers.BooleanField()
    transaction_no = serializers.CharField(allow_null=True, required=False)
    amount = serializers.CharField(allow_null=True, required=False)


class CodComplianceSerializer(serializers.Serializer):
    order_type = serializers.CharField(allow_blank=True)
    collection_status = serializers.CharField(allow_blank=True)
    cod_amount = serializers.CharField(allow_blank=True)
    is_cod_order = serializers.BooleanField()
    is_collection_pending = serializers.BooleanField()
    shipment_status = serializers.CharField(allow_blank=True)
    treasury = TreasuryPostingSerializer()


class PodUploadComplianceWrapperSerializer(serializers.Serializer):
    pod = PodComplianceSerializer()


class CodCollectionComplianceWrapperSerializer(serializers.Serializer):
    cod = CodComplianceSerializer()


class PodUploadResponseDataSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=('upload_pod',))
    execution = ActionExecutionResultSerializer()
    workflow = WorkflowRefreshSerializer()
    compliance = PodUploadComplianceWrapperSerializer()


class CodCollectionResponseDataSerializer(serializers.Serializer):
    operation = serializers.ChoiceField(choices=('collect_cod',))
    execution = ActionExecutionResultSerializer()
    workflow = WorkflowRefreshSerializer()
    compliance = CodCollectionComplianceWrapperSerializer()
