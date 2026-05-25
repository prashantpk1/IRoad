"""
mobile_api/services/driver_job_list_dto.py

Mobile job-list data contracts (flat list cards + pagination meta).
"""
from __future__ import annotations

from typing import Any, TypedDict


class JobRouteProjectionDTO(TypedDict):
    summary: str
    from_label: str
    to_label: str


class JobTruckSummaryDTO(TypedDict, total=False):
    truck_id: str | None
    truck_code: str
    plate_number: str
    truck_status: str | None
    sourcing_mode: str | None


class JobLatestActionSummaryDTO(TypedDict, total=False):
    log_id: str
    log_no: str
    log_date: str | None
    action_code: str | None
    action_label: str | None


class JobOperationalIndicatorsDTO(TypedDict):
    needs_pod: bool
    needs_cod: bool
    is_active: bool
    is_empty_move: bool


class JobCardDTO(TypedDict, total=False):
    """
    Unified flat job card (shipment + movement list feeds).

    Primary mobile fields are top-level; ``route`` / ``truck`` / ``indicators``
    duplicate the same data in compact form for clients that expect nesting.
    """

    job_id: str
    job_type: str
    job_no: str
    current_status: str
    route_summary: str
    from_location: str
    to_location: str
    truck_id: str | None
    truck_code: str
    plate_number: str
    truck_status: str | None
    truck_sourcing_mode: str | None
    latest_action_summary: JobLatestActionSummaryDTO | None
    next_action_hint: str | None
    pod_status: str
    cod_status: str
    collection_status: str
    needs_pod: bool
    needs_cod: bool
    is_active: bool
    is_empty_move: bool
    is_pod_pending: bool
    is_cod_pending: bool
    is_cod_order: bool
    updated_at: str | None
    created_at: str | None
    route: JobRouteProjectionDTO
    truck: JobTruckSummaryDTO | None
    indicators: JobOperationalIndicatorsDTO
    priority: JobOperationalIndicatorsDTO


class ShipmentJobCardDTO(JobCardDTO, total=False):
    shipment_id: str
    shipment_no: str
    movement_id: None
    movement_no: None
    booking_no: str | None
    order_type: str
    shipment_date: str | None


class MovementJobCardDTO(JobCardDTO, total=False):
    movement_id: str
    movement_no: str
    shipment_id: str | None
    shipment_no: str | None
    movement_source: str
    empty_move_reason: str
    movement_date: str | None


class JobSummaryCountersDTO(TypedDict):
    active_shipments: int
    completed_shipments: int
    cancelled_shipments: int
    active_movements: int
    completed_movements: int
    cancelled_movements: int
    pod_pending: int
    cod_pending: int


class JobSummaryDTO(TypedDict):
    counters: JobSummaryCountersDTO
    entity_types: tuple[str, ...]


class JobListMetaDTO(TypedDict):
    tab: str
    queue: str
    sort: str
    entity_type: str
    tab_locked: bool
    queue_locked: bool


class JobListResultDTO(TypedDict, total=False):
    success: bool
    error: str
    items: list[dict[str, Any]]
    queryset: Any
    meta: JobListMetaDTO
