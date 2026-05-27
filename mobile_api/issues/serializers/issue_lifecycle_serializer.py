"""
mobile_api/issues/serializers/issue_lifecycle_serializer.py
"""
from __future__ import annotations

from rest_framework import serializers


class IssueLifecycleRequestSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
