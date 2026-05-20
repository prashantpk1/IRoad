"""
mobile_api/services/driver_dashboard_dto.py

Typed shapes for the driver home dashboard payload (documentation + IDE hints).

Serialized output is produced by ``driver_dashboard_service`` and
``serializers.driver_dashboard``; keys match these structures.
"""
from __future__ import annotations

from typing import Any, TypedDict


class WelcomeDriverProfileDTO(TypedDict):
    driver_id: str
    driver_code: str
    name: str
    profile_photo_url: str | None
    driver_status: str
    driver_type: str


class WelcomeRoleDTO(TypedDict):
    role_name: str
    user_status: str


class WelcomeOrganizationDTO(TypedDict):
    tenant_id: str
    schema_name: str
    organization_name: str
    company_name: str
    logo_url: str


class WelcomeAssignedTruckDTO(TypedDict, total=False):
    truck_id: str
    truck_code: str
    plate_number: str
    truck_status: str | None
    sourcing_mode: str | None
    truck_type_label: str


class WelcomeCurrentAssignmentDTO(TypedDict):
    assignment_id: str
    assigned_from: str | None
    assigned_to: str | None
    assignment_status: str
    is_current: bool


class WelcomeLocaleDTO(TypedDict):
    request_language: str
    supported_languages: list[str]
    timezone: str
    system_language: str
    date_format: str
    number_format: str
    negative_format: str


class WelcomeOperationalContextDTO(TypedDict, total=False):
    tenant_schema: str
    driver_assignment_required: bool
    has_assigned_truck: bool
    has_current_assignment: bool
    driver_status: str
    assignment_status: str | None
    counters_snapshot: dict[str, int] | None


class DashboardWelcomeDTO(TypedDict, total=False):
    """Nested welcome envelope + flat aliases for legacy clients."""

    driver_id: str
    driver_code: str
    name: str
    profile_photo_url: str | None
    role_name: str
    organization_name: str
    tenant_id: str
    schema_name: str
    assigned_truck: WelcomeAssignedTruckDTO | None
    assignment_status: str | None
    plate_number: str
    display_name: dict[str, str]
    driver: WelcomeDriverProfileDTO
    role: WelcomeRoleDTO
    organization: WelcomeOrganizationDTO
    current_assignment: WelcomeCurrentAssignmentDTO | None
    locale: WelcomeLocaleDTO
    operational_context: WelcomeOperationalContextDTO


class DashboardCountersDTO(TypedDict):
    active_shipments: int
    active_movements: int
    pending_pod: int
    cod_pending: int
    pending_actions: int
    completed_today: int
    completed_this_week: int


class CurrentJobShipmentDTO(TypedDict, total=False):
    shipment_id: str
    shipment_no: str
    shipment_status: str
    booking_no: str | None
    order_type: str
    sourcing_mode: str
    shipment_date: str | None


class CurrentJobMovementDTO(TypedDict):
    movement_id: str
    movement_no: str
    status: str
    movement_date: str | None
    movement_source: str


class CurrentJobRouteDTO(TypedDict):
    summary: str
    from_label: str
    to_label: str


class CurrentJobStatusDTO(TypedDict):
    shipment_status: str
    movement_status: str | None
    operational_stage: str
    has_active_movement: bool


class CurrentJobPodDTO(TypedDict):
    status: str
    is_pending: bool
    needs_attention: bool
    pod_type: str


class CurrentJobCodDTO(TypedDict):
    order_type: str
    cod_amount: str
    collection_status: str
    is_cod_order: bool
    is_collection_pending: bool


class CurrentJobLatestActionDTO(TypedDict, total=False):
    log_id: str
    log_no: str
    log_date: str | None
    action_code: str | None
    action_label: str | None


class DashboardCurrentJobDTO(TypedDict, total=False):
    has_active_job: bool
    shipment: CurrentJobShipmentDTO | None
    movement: CurrentJobMovementDTO | None
    status: CurrentJobStatusDTO | None
    route: CurrentJobRouteDTO | None
    truck: dict[str, Any] | None
    latest_action: CurrentJobLatestActionDTO | None
    pod: CurrentJobPodDTO | None
    cod: CurrentJobCodDTO | None
    next_action_hint: str | None
    shipment_id: str | None
    shipment_no: str | None
    shipment_status: str | None
    booking_no: str | None
    route_summary: str
    pod_status: str | None
    collection_status: str | None
    order_type: str | None
    operational_stage: str | None


class QuickActionExecutionDTO(TypedDict, total=False):
    phase: str
    route_key: str
    deep_link: str
    api_path: str | None
    http_method: str | None


class DashboardQuickActionDTO(TypedDict, total=False):
    id: str
    label: str
    sort_order: int
    visible: bool
    enabled: bool
    reason_code: str | None
    reason_message: str | None
    required_capabilities: list[str]
    execution: QuickActionExecutionDTO
    shipment_id: str | None
    movement_id: str | None


class DashboardQuickActionsMetaDTO(TypedDict):
    total_visible: int
    total_enabled: int


class DashboardNotificationFcmDTO(TypedDict):
    push_enabled: bool
    device_token_registered: bool
    channel: str
    inbox_deep_link: str
    register_token_route: str


class DashboardNotificationSummaryDTO(TypedDict):
    unread_count: int
    critical_count: int
    assignment_count: int
    operational_warnings_count: int
    items: list[dict[str, Any]]
    fcm: DashboardNotificationFcmDTO


class DashboardRecentActivityItemDTO(TypedDict, total=False):
    activity_type: str
    occurred_at: str | None
    title: str
    route_summary: str
    action_code: str | None
    action_label: str | None
    shipment_id: str | None
    shipment_no: str | None
    movement_id: str | None
    movement_no: str | None
    pod_status: str | None
    document_id: str | None
    source: str
    log_id: str | None
    log_no: str | None
    log_date: str | None


class DashboardRecentActivityFeedDTO(TypedDict):
    limit: int
    items: list[DashboardRecentActivityItemDTO]


class DashboardDriverSummaryDTO(TypedDict, total=False):
    driver_id: str
    driver_code: str
    name: str
    profile_photo_url: str | None
    driver_status: str
    email: str
    full_name: str
    role_name: str
    organization_name: str
    assigned_truck: dict[str, Any] | None


class DashboardTimestampsDTO(TypedDict):
    generated_at: str
    timezone: str
    locale: str


class DashboardPayloadDTO(TypedDict):
    variant: str
    welcome: DashboardWelcomeDTO
    driver_summary: DashboardDriverSummaryDTO
    counters: DashboardCountersDTO
    current_job: DashboardCurrentJobDTO
    quick_actions: list[DashboardQuickActionDTO]
    quick_actions_meta: DashboardQuickActionsMetaDTO
    notifications_summary: DashboardNotificationSummaryDTO
    recent_activity: list[DashboardRecentActivityItemDTO]
    timestamps: DashboardTimestampsDTO
    generated_at: str
