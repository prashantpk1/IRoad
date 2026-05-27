"""
mobile_api/payment_collection/serializers/payment_collection_serializer.py
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from mobile_api.execution.evidence.constants import EXECUTION_MEDIA_MAX_ITEMS


class PaymentProofMediaSerializer(serializers.Serializer):
    media_type = serializers.ChoiceField(
        choices=['photo', 'video', 'document', 'signature'],
        required=False,
        allow_blank=True,
    )
    file_ref = serializers.CharField(required=False, allow_blank=True, max_length=500)
    file_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    mime_type = serializers.CharField(required=False, allow_blank=True, max_length=128)
    checksum = serializers.CharField(required=False, allow_blank=True, max_length=128)
    captured_at = serializers.DateTimeField(required=False, allow_null=True)
    sort_order = serializers.IntegerField(required=False, default=0)


class PaymentCollectionRequestSerializer(serializers.Serializer):
    client_payment_id = serializers.CharField(max_length=128)
    shipment_id = serializers.CharField(max_length=64)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    payment_mode = serializers.CharField(required=False, allow_blank=True, default='')
    proof_media = PaymentProofMediaSerializer(many=True, required=False, default=list)

    def validate_client_payment_id(self, value: str) -> str:
        token = (value or '').strip()
        if not token:
            raise serializers.ValidationError(
                str(_('mobile.payment_collection.client_payment_id_required')),
                code='client_payment_id_required',
            )
        return token

    def validate_proof_media(self, value: list[dict]) -> list[dict]:
        if len(value or []) > EXECUTION_MEDIA_MAX_ITEMS:
            raise serializers.ValidationError(
                str(_('mobile.jobs.execute.media_limit_exceeded')),
                code='media_limit_exceeded',
            )
        return value or []

