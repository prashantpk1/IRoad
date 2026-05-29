"""
mobile_api/wallet/serializers/wallet_serializer.py

DRF validation shell for Wallet API ``data`` payloads.
"""
from __future__ import annotations

from rest_framework import serializers


class WalletListResponseSerializer(serializers.Serializer):
    """GET /driver/wallet/ list envelope."""

    summary = serializers.DictField(required=False, default=dict)
    items = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    count = serializers.IntegerField(required=False, default=0)
    results_found = serializers.IntegerField(required=False, default=0)
    total_records = serializers.IntegerField(required=False, default=0)
    total_pages = serializers.IntegerField(required=False, default=0)
    current_page = serializers.IntegerField(required=False, default=1)
    page_size = serializers.IntegerField(required=False, default=10)


class WalletDetailResponseSerializer(serializers.Serializer):
    """GET /driver/wallet/transactions/<id>/ detail envelope."""

    summary = serializers.DictField(required=False, default=dict)
    transaction = serializers.DictField(required=False, default=dict)
    shipment = serializers.DictField(required=False, default=dict)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    wallet_projection_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default='1',
    )
    read_only = serializers.BooleanField(required=False, default=True)
