"""
mobile_api/hard_pod/serializers/hard_pod_list_serializer.py

Optional query params for Hard POD list (read-only).
"""
from __future__ import annotations

from rest_framework import serializers


class HardPodListQuerySerializer(serializers.Serializer):
    """GET query parameters — reserved for future pagination filters."""

    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=50,
    )
