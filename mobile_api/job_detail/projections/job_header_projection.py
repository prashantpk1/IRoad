"""
mobile_api/job_detail/projections/job_header_projection.py

``job`` section — identity, status labels, assignment, route summary (read-only).
"""
from __future__ import annotations

from typing import Any

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext


def build_job_header(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Build the unified ``job`` header block.

    TODO:
      - shipment: shipment_no, booking_item_type, addresses, client, driver slice
      - movement: movement_no, from/to, movement_source, empty-move flags
      - include reconciled authoritative status when available
    """
    _ = request
    base = {
        'job_type': context.job_type,
        'job_id': context.job_id,
        'job_no': '',
        'entity_type': context.job_type,
    }
    if context.job_type == 'shipment' and context.shipment is not None:
        # TODO: map shipment + booking fields
        base['job_no'] = str(getattr(context.shipment, 'shipment_no', '') or '')
        return base
    if context.job_type == 'movement' and context.movement is not None:
        # TODO: map movement fields
        base['job_no'] = str(getattr(context.movement, 'movement_no', '') or '')
        return base
    return base
