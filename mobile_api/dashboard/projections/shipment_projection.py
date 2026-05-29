"""
mobile_api/dashboard/projections/shipment_projection.py

Pure functions: shipment → dashboard shipment slice nested under job card.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.job_booking_meta import (
    resolve_client_name,
    resolve_execution_date,
)
from mobile_api.helpers.order_type import resolve_order_type_text


def build_active_shipment_slice(
    shipment: Any | None,
    *,
    booking: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Active shipment block for the booking job card (includes route + addresses).
    """
    if shipment is None:
        return {}

    from mobile_api.job_detail.projections.job_location_projection import (
        build_shipment_location_block,
    )

    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)
    payload: dict[str, Any] = {
        'shipment_id': str(shipment_id) if shipment_id is not None else '',
        'shipment_no': str(getattr(shipment, 'shipment_no', '') or ''),
        'booking_item_type': str(getattr(shipment, 'booking_item_type', '') or ''),
        'shipment_status': str(getattr(shipment, 'shipment_status', '') or ''),
        'trip_type': str(getattr(shipment, 'trip_type', '') or ''),
        'job_type': 'shipment',
        'job_id': str(shipment_id) if shipment_id is not None else '',
        'job_no': str(getattr(shipment, 'shipment_no', '') or ''),
        'order_type': resolve_order_type_text(shipment=shipment, booking=booking),
        'client_name': resolve_client_name(
            shipment=shipment,
            booking=booking,
            request=request,
        ),
        'execution_date': resolve_execution_date(
            shipment=shipment,
            booking=booking,
        ),
    }
    payload.update(
        build_shipment_location_block(
            shipment,
            booking=booking,
            request=request,
        ),
    )
    return payload


def build_shipment_card(
    shipment: Any,
    *,
    tenant_schema: str,
    booking: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Map a shipment to the shipment slice of ``current_job``."""
    _ = tenant_schema
    return build_active_shipment_slice(
        shipment,
        booking=booking,
        request=request,
    )
