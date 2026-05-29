"""
mobile_api/job_detail/projections/job_header_projection.py

``job`` section — identity, status labels, assignment, route summary (read-only).
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.order_type import resolve_order_type_text
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.job_location_projection import (
    build_movement_location_block,
    build_shipment_location_block,
)


def build_job_header(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Build the unified ``job`` header block.

    Includes route, pickup (loading), and drop (delivery) addresses for navigation.
    """
    base: dict[str, Any] = {
        'job_type': context.job_type,
        'job_id': context.job_id,
        'job_no': '',
        'entity_type': context.job_type,
        'order_type': '',
        'route': {},
        'pickup_address': {},
        'drop_address': {},
    }

    if context.job_type == 'shipment' and context.shipment is not None:
        base['job_no'] = str(getattr(context.shipment, 'shipment_no', '') or '')
        base['order_type'] = resolve_order_type_text(
            shipment=context.shipment,
            booking=context.booking,
        )
        base.update(
            build_shipment_location_block(
                context.shipment,
                booking=context.booking,
                request=request,
            ),
        )
        return base

    if context.job_type == 'movement' and context.movement is not None:
        base['job_no'] = str(getattr(context.movement, 'movement_no', '') or '')
        movement_shipment = getattr(context.movement, 'shipment', None)
        base['order_type'] = resolve_order_type_text(
            shipment=movement_shipment,
            booking=context.booking
            or getattr(context.movement, 'booking', None),
        )
        base.update(
            build_movement_location_block(context.movement, request=request),
        )
        return base

    return base
