"""
mobile_api/dashboard/projections/job_location_dashboard.py

Route + pickup/drop blocks for dashboard ``active_job`` / ``active_shipment``.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.job_booking_meta import (
    resolve_client_name,
    resolve_execution_date,
)
from mobile_api.helpers.order_type import resolve_order_type_text


def build_dashboard_active_job(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    movement: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Mobile ``active_job`` slice (same location fields as Job Detail ``data.job``).

    Shipment job takes precedence when both shipment and movement are set.
    """
    from mobile_api.job_detail.projections.job_location_projection import (
        build_movement_location_block,
        build_shipment_location_block,
    )

    if shipment is not None:
        shipment_id = getattr(shipment, 'shipment_id', None) or getattr(
            shipment, 'pk', None
        )
        block = {
            'job_type': 'shipment',
            'job_id': str(shipment_id) if shipment_id is not None else '',
            'job_no': str(getattr(shipment, 'shipment_no', '') or ''),
            'entity_type': 'shipment',
            'order_type': resolve_order_type_text(
                shipment=shipment,
                booking=booking,
            ),
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
        block.update(
            build_shipment_location_block(
                shipment,
                booking=booking,
                request=request,
            ),
        )
        return block

    if movement is not None:
        movement_id = getattr(movement, 'movement_id', None) or getattr(
            movement, 'pk', None
        )
        movement_shipment = getattr(movement, 'shipment', None)
        movement_booking = booking or getattr(movement, 'booking', None)
        block = {
            'job_type': 'movement',
            'job_id': str(movement_id) if movement_id is not None else '',
            'job_no': str(getattr(movement, 'movement_no', '') or ''),
            'entity_type': 'movement',
            'order_type': resolve_order_type_text(
                shipment=movement_shipment,
                booking=movement_booking,
            ),
            'client_name': resolve_client_name(
                shipment=movement_shipment,
                booking=movement_booking,
                request=request,
            ),
            'execution_date': resolve_execution_date(
                shipment=movement_shipment,
                booking=movement_booking,
            ),
        }
        block.update(build_movement_location_block(movement, request=request))
        return block

    return {}
