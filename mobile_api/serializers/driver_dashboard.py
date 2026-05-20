"""
mobile_api/serializers/driver_dashboard.py

Read-only serializers for the driver home dashboard envelope sections.
"""
from __future__ import annotations

from rest_framework import serializers

from mobile_api.serializers.driver_dashboard_activity import (
    DashboardRecentActivityItemSerializer,
)
from mobile_api.serializers.driver_dashboard_notifications import (
    DashboardNotificationsSummarySerializer,
)
from mobile_api.serializers.driver_dashboard_quick_actions import (
    DashboardQuickActionSerializer,
)


class DashboardAssignedTruckSerializer(serializers.Serializer):
    truck_id = serializers.UUIDField(allow_null=True, required=False)
    truck_code = serializers.CharField(allow_blank=True, required=False)
    plate_number = serializers.CharField(allow_blank=True, required=False)
    truck_status = serializers.CharField(allow_null=True, required=False)
    sourcing_mode = serializers.CharField(allow_null=True, required=False)
    truck_type_label = serializers.CharField(allow_blank=True, required=False)


class WelcomeDriverProfileSerializer(serializers.Serializer):
    driver_id = serializers.UUIDField()
    driver_code = serializers.CharField()
    name = serializers.CharField()
    profile_photo_url = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        required=False,
    )
    driver_status = serializers.CharField()
    driver_type = serializers.CharField(allow_blank=True)


class WelcomeRoleSerializer(serializers.Serializer):
    role_name = serializers.CharField(allow_blank=True)
    user_status = serializers.CharField(allow_blank=True)


class WelcomeOrganizationSerializer(serializers.Serializer):
    tenant_id = serializers.CharField(allow_blank=True)
    schema_name = serializers.CharField(allow_blank=True)
    organization_name = serializers.CharField(allow_blank=True)
    company_name = serializers.CharField(allow_blank=True)
    logo_url = serializers.CharField(allow_blank=True)


class WelcomeCurrentAssignmentSerializer(serializers.Serializer):
    assignment_id = serializers.UUIDField()
    assigned_from = serializers.CharField(allow_null=True, required=False)
    assigned_to = serializers.CharField(allow_null=True, required=False)
    assignment_status = serializers.CharField()
    is_current = serializers.BooleanField()


class WelcomeLocaleSerializer(serializers.Serializer):
    request_language = serializers.CharField()
    supported_languages = serializers.ListField(child=serializers.CharField())
    timezone = serializers.CharField()
    system_language = serializers.CharField()
    date_format = serializers.CharField()
    number_format = serializers.CharField()
    negative_format = serializers.CharField()


class WelcomeOperationalCountersSnapshotSerializer(serializers.Serializer):
    active_shipments = serializers.IntegerField(min_value=0, required=False)
    active_movements = serializers.IntegerField(min_value=0, required=False)
    pending_pod = serializers.IntegerField(min_value=0, required=False)
    cod_pending = serializers.IntegerField(min_value=0, required=False)
    pending_actions = serializers.IntegerField(min_value=0, required=False)
    completed_today = serializers.IntegerField(min_value=0, required=False)
    completed_this_week = serializers.IntegerField(min_value=0, required=False)


class WelcomeOperationalContextSerializer(serializers.Serializer):
    tenant_schema = serializers.CharField()
    driver_assignment_required = serializers.BooleanField()
    has_assigned_truck = serializers.BooleanField()
    has_current_assignment = serializers.BooleanField()
    driver_status = serializers.CharField(allow_blank=True)
    assignment_status = serializers.CharField(allow_null=True, required=False)
    counters_snapshot = WelcomeOperationalCountersSnapshotSerializer(
        allow_null=True,
        required=False,
    )


class DashboardDisplayNameSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True)
    name_en = serializers.CharField(allow_blank=True, required=False)
    name_ar = serializers.CharField(allow_blank=True, required=False)


class DashboardTimestampsSerializer(serializers.Serializer):
    generated_at = serializers.CharField()
    timezone = serializers.CharField(allow_blank=True)
    locale = serializers.CharField(allow_blank=True)


class DashboardDriverSummarySerializer(serializers.Serializer):
    driver_id = serializers.UUIDField()
    driver_code = serializers.CharField()
    name = serializers.CharField()
    profile_photo_url = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        required=False,
    )
    driver_status = serializers.CharField()
    driver_type = serializers.CharField(allow_blank=True)
    mobile_number = serializers.CharField(allow_blank=True)
    whatsapp_number = serializers.CharField(allow_blank=True)
    email = serializers.EmailField(allow_blank=True)
    full_name = serializers.CharField(allow_blank=True)
    username = serializers.CharField(allow_blank=True)
    role_name = serializers.CharField(allow_blank=True)
    user_status = serializers.CharField(allow_blank=True)
    tenant_id = serializers.CharField(allow_blank=True)
    schema_name = serializers.CharField(allow_blank=True)
    organization_name = serializers.CharField(allow_blank=True)
    assigned_truck = DashboardAssignedTruckSerializer(
        allow_null=True,
        required=False,
    )
    assignment_status = serializers.CharField(allow_null=True, required=False)


class DashboardWelcomeSerializer(serializers.Serializer):
    """Welcome header — nested projections + flat aliases."""

    driver_id = serializers.UUIDField()
    driver_code = serializers.CharField()
    name = serializers.CharField()
    profile_photo_url = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        required=False,
    )
    role_name = serializers.CharField(allow_blank=True)
    organization_name = serializers.CharField(allow_blank=True)
    tenant_id = serializers.CharField(allow_blank=True)
    schema_name = serializers.CharField(allow_blank=True)
    assigned_truck = DashboardAssignedTruckSerializer(
        allow_null=True,
        required=False,
    )
    assignment_status = serializers.CharField(allow_null=True, required=False)
    plate_number = serializers.CharField(allow_blank=True)
    display_name = DashboardDisplayNameSerializer()
    driver = WelcomeDriverProfileSerializer()
    role = WelcomeRoleSerializer()
    organization = WelcomeOrganizationSerializer()
    current_assignment = WelcomeCurrentAssignmentSerializer(
        allow_null=True,
        required=False,
    )
    locale = WelcomeLocaleSerializer()
    operational_context = WelcomeOperationalContextSerializer()


class DashboardCountersSerializer(serializers.Serializer):
    active_shipments = serializers.IntegerField(min_value=0)
    active_movements = serializers.IntegerField(min_value=0)
    pending_pod = serializers.IntegerField(min_value=0)
    cod_pending = serializers.IntegerField(min_value=0)
    pending_actions = serializers.IntegerField(min_value=0)
    completed_today = serializers.IntegerField(min_value=0)
    completed_this_week = serializers.IntegerField(min_value=0)


class DashboardTruckCardSerializer(serializers.Serializer):
    truck_id = serializers.UUIDField()
    truck_code = serializers.CharField()
    plate_number = serializers.CharField(allow_blank=True)
    truck_status = serializers.CharField(allow_null=True, required=False)
    sourcing_mode = serializers.CharField(allow_null=True, required=False)


class DashboardMovementCardSerializer(serializers.Serializer):
    movement_id = serializers.UUIDField()
    movement_no = serializers.CharField()
    status = serializers.CharField()
    movement_date = serializers.CharField(allow_null=True, required=False)


class DashboardLatestActionSerializer(serializers.Serializer):
    log_id = serializers.UUIDField()
    log_no = serializers.CharField()
    log_date = serializers.CharField(allow_null=True, required=False)
    action_code = serializers.CharField(allow_null=True, required=False)
    action_label = serializers.CharField(allow_null=True, required=False)


class CurrentJobShipmentSerializer(serializers.Serializer):
    shipment_id = serializers.UUIDField()
    shipment_no = serializers.CharField()
    shipment_status = serializers.CharField()
    booking_no = serializers.CharField(allow_null=True, required=False)
    order_type = serializers.CharField(allow_blank=True)
    sourcing_mode = serializers.CharField(allow_blank=True)
    shipment_date = serializers.CharField(allow_null=True, required=False)


class CurrentJobMovementSerializer(serializers.Serializer):
    movement_id = serializers.UUIDField()
    movement_no = serializers.CharField()
    status = serializers.CharField()
    movement_date = serializers.CharField(allow_null=True, required=False)
    movement_source = serializers.CharField(allow_blank=True)


class CurrentJobRouteSerializer(serializers.Serializer):
    summary = serializers.CharField(allow_blank=True)
    from_label = serializers.CharField(allow_blank=True)
    to_label = serializers.CharField(allow_blank=True)


class CurrentJobStatusSerializer(serializers.Serializer):
    shipment_status = serializers.CharField()
    movement_status = serializers.CharField(allow_null=True, required=False)
    operational_stage = serializers.CharField()
    has_active_movement = serializers.BooleanField()


class CurrentJobPodSerializer(serializers.Serializer):
    status = serializers.CharField(allow_blank=True)
    is_pending = serializers.BooleanField()
    needs_attention = serializers.BooleanField()
    pod_type = serializers.CharField(allow_blank=True)


class CurrentJobCodSerializer(serializers.Serializer):
    order_type = serializers.CharField(allow_blank=True)
    cod_amount = serializers.CharField()
    collection_status = serializers.CharField(allow_blank=True)
    is_cod_order = serializers.BooleanField()
    is_collection_pending = serializers.BooleanField()


class DashboardCurrentJobSerializer(serializers.Serializer):
    has_active_job = serializers.BooleanField()
    shipment = CurrentJobShipmentSerializer(allow_null=True, required=False)
    movement = CurrentJobMovementSerializer(allow_null=True, required=False)
    status = CurrentJobStatusSerializer(allow_null=True, required=False)
    route = CurrentJobRouteSerializer(allow_null=True, required=False)
    truck = DashboardTruckCardSerializer(allow_null=True, required=False)
    latest_action = DashboardLatestActionSerializer(
        allow_null=True,
        required=False,
    )
    pod = CurrentJobPodSerializer(allow_null=True, required=False)
    cod = CurrentJobCodSerializer(allow_null=True, required=False)
    next_action_hint = serializers.CharField(allow_null=True, required=False)
    shipment_id = serializers.UUIDField(allow_null=True, required=False)
    shipment_no = serializers.CharField(allow_null=True, required=False)
    shipment_status = serializers.CharField(allow_null=True, required=False)
    booking_no = serializers.CharField(allow_null=True, required=False)
    route_summary = serializers.CharField(allow_blank=True)
    pod_status = serializers.CharField(allow_null=True, required=False)
    collection_status = serializers.CharField(allow_null=True, required=False)
    order_type = serializers.CharField(allow_blank=True, required=False)
    operational_stage = serializers.CharField(allow_null=True, required=False)


class DashboardQuickActionsMetaSerializer(serializers.Serializer):
    total_visible = serializers.IntegerField(min_value=0)
    total_enabled = serializers.IntegerField(min_value=0)


def serialize_dashboard_payload(payload: dict, *, request=None) -> dict:
    """
    Serialize pre-built dashboard dict for API output.

    When ``MOBILE_API_DASHBOARD_FAST_SERIALIZE`` is True (default), returns the
    trusted service payload without re-walking ~15 nested DRF serializers.
    """
    from django.conf import settings

    if getattr(settings, 'MOBILE_API_DASHBOARD_FAST_SERIALIZE', True):
        return payload
    return DriverDashboardSerializer(
        instance=payload,
        context={'request': request},
    ).data


class DriverDashboardSerializer(serializers.Serializer):
    """
    Top-level dashboard ``data`` object for mobile clients.

    Used by both ``/driver/dashboard/`` and ``/driver/dashboard/summary/``.
    """

    variant = serializers.ChoiceField(choices=('full', 'summary'))
    welcome = DashboardWelcomeSerializer()
    driver_summary = DashboardDriverSummarySerializer()
    counters = DashboardCountersSerializer()
    current_job = DashboardCurrentJobSerializer()
    quick_actions = DashboardQuickActionSerializer(many=True)
    quick_actions_meta = DashboardQuickActionsMetaSerializer()
    notifications_summary = DashboardNotificationsSummarySerializer()
    recent_activity = DashboardRecentActivityItemSerializer(many=True)
    timestamps = DashboardTimestampsSerializer()
    generated_at = serializers.CharField()
