"""
mobile_api/helpers/job_list_query.py

Driver-scoped ORM querysets for job list feeds (``only`` + minimal joins).

Performance rules:
- No timelines / action-log prefetch on list queryset.
- ``truck__truck_type`` omitted (not used by job card projection).
- Movement ``shipment`` via ``Prefetch`` with ``only()`` on nested rows.
"""
from __future__ import annotations

from django.db.models import Prefetch, QuerySet

from mobile_api.helpers.job_list_driver_scope import filter_shipments_for_driver
from mobile_api.helpers.job_list_security import secure_movement_queryset_for_driver

# Shipment card fields — FK ids required when select_related addresses/truck/booking.
SHIPMENT_JOB_LIST_ONLY = (
    'shipment_id',
    'shipment_no',
    'shipment_status',
    'shipment_date',
    'order_type',
    'sourcing_mode',
    'pod_status',
    'pod_type',
    'collection_status',
    'cod_amount',
    'route_display',
    'updated_at',
    'created_at',
    'mobile_operational_rank',
    'booking_id',
    'truck_id',
    'driver_id',
    'loading_address_id',
    'delivery_address_id',
)

SHIPMENT_JOB_LIST_RELATED = (
    'truck',
    'booking',
    'loading_address',
    'delivery_address',
)

# Nested shipment on movement cards (next-action + route fallback).
MOVEMENT_LINKED_SHIPMENT_ONLY = (
    'shipment_id',
    'shipment_no',
    'shipment_status',
    'order_type',
    'pod_status',
    'collection_status',
    'cod_amount',
    'route_display',
    'loading_address_id',
    'delivery_address_id',
)

MOVEMENT_LINKED_SHIPMENT_RELATED = (
    'loading_address',
    'delivery_address',
)

# Movement card fields.
MOVEMENT_JOB_LIST_ONLY = (
    'movement_id',
    'movement_no',
    'status',
    'movement_date',
    'movement_source',
    'empty_move_reason',
    'updated_at',
    'created_at',
    'shipment_id',
    'truck_id',
    'driver_id',
    'from_location_point_id',
    'to_location_point_id',
)

LOCATION_LABEL_ONLY = (
    'location_id',
    'display_label',
    'location_name_english',
    'location_name_arabic',
)


def _movement_shipment_prefetch():
    from tenant_workspace.models import TenantShipment

    return Prefetch(
        'shipment',
        queryset=TenantShipment.objects.only(
            *MOVEMENT_LINKED_SHIPMENT_ONLY,
        ).select_related(*MOVEMENT_LINKED_SHIPMENT_RELATED),
    )


def base_shipment_job_queryset(driver) -> QuerySet:
    """Driver-scoped shipments with lightweight joins for job cards."""
    return (
        filter_shipments_for_driver(driver)
        .only(*SHIPMENT_JOB_LIST_ONLY)
        .select_related(*SHIPMENT_JOB_LIST_RELATED)
    )


def base_movement_job_queryset(driver) -> QuerySet:
    """Driver-scoped movements with lightweight joins for job cards."""
    return (
        secure_movement_queryset_for_driver(driver)
        .only(*MOVEMENT_JOB_LIST_ONLY)
        .select_related('truck', 'from_location_point', 'to_location_point')
        .prefetch_related(_movement_shipment_prefetch())
    )
