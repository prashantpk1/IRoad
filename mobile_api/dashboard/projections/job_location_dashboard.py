"""
mobile_api/dashboard/projections/job_location_dashboard.py

Route + pickup/drop blocks for dashboard ``active_job`` / ``active_shipment``.
"""
from __future__ import annotations

from typing import Any

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
        block = {
            'job_type': 'movement',
            'job_id': str(movement_id) if movement_id is not None else '',
            'job_no': str(getattr(movement, 'movement_no', '') or ''),
            'entity_type': 'movement',
        }
        block.update(build_movement_location_block(movement, request=request))
        return block

    return {}
