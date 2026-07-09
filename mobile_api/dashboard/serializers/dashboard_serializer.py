"""
mobile_api/dashboard/serializers/dashboard_serializer.py

DRF validation shell for the unified dashboard response contract.
"""
from __future__ import annotations

from rest_framework import serializers


class DashboardCurrentJobSerializer(serializers.Serializer):
    """Nested ``current_job`` booking card (includes ``active_shipment``)."""


class DashboardActiveJobSerializer(serializers.Serializer):
    """Top-level ``active_job`` — job_id + route + pickup/drop (Job Detail parity)."""

    # TODO: Add explicit fields when contract stabilizes.


class DashboardCurrentEmptyMoveSerializer(serializers.Serializer):
    """Nested ``current_empty_move``."""

    # TODO: Add explicit fields when contract stabilizes.


class DashboardWorkflowSerializer(serializers.Serializer):
    """Nested ``workflow``."""

    # TODO: next_action, allowed_actions, stage, etc.


class DashboardPodCodSummarySerializer(serializers.Serializer):
    """Nested ``pod_cod_summary``."""


class DashboardTimelineSummarySerializer(serializers.Serializer):
    """Nested ``timeline_summary``."""


class DashboardAlertsSerializer(serializers.Serializer):
    """Nested ``alerts``."""


class DashboardSyncMetadataSerializer(serializers.Serializer):
    """Nested ``sync_metadata``."""


class DashboardResponseSerializer(serializers.Serializer):
    """
    Validates the dashboard ``data`` payload shape before envelope wrap.

    Skeleton: permissive dict fields until the contract is finalized.
    """

    current_job = serializers.DictField(required=False, default=dict)
    active_job = serializers.DictField(required=False, default=dict)
    current_empty_move = serializers.DictField(required=False, default=dict)
    workflow = serializers.DictField(required=False, default=dict)
    next_action_hint = serializers.DictField(required=False, default=dict)
    on_call = serializers.DictField(required=False, default=dict)
    pod_cod_summary = serializers.DictField(required=False, default=dict)
    timeline_summary = serializers.DictField(required=False, default=dict)
    alerts = serializers.DictField(required=False, default=dict)
    sync_metadata = serializers.DictField(required=False, default=dict)
