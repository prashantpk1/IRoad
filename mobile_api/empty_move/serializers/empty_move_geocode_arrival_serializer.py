"""Request validation for empty move geocode arrival API."""
from __future__ import annotations

from rest_framework import serializers


class EmptyMoveGeocodeArrivalSerializer(serializers.Serializer):
    """
    Validates GPS coordinates sent to geocode the arrival address of an empty move.
    """
    latitude = serializers.FloatField(required=True)
    longitude = serializers.FloatField(required=True)
