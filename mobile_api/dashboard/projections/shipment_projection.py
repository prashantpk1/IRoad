"""
mobile_api/dashboard/projections/shipment_projection.py

Pure functions: shipment → dashboard shipment slice nested under job card.
"""
from __future__ import annotations

from typing import Any


def build_active_shipment_slice(shipment: Any | None) -> dict[str, Any]:
    """
    Minimal active-shipment block for the booking job card.

    Full shipment card projection is expanded in later dashboard phases.
    """
    if shipment is None:
        return {}

    shipment_id = getattr(shipment, 'shipment_id', None) or getattr(shipment, 'pk', None)
    return {
        'shipment_id': str(shipment_id) if shipment_id is not None else '',
        'shipment_no': str(getattr(shipment, 'shipment_no', '') or ''),
        'booking_item_type': str(getattr(shipment, 'booking_item_type', '') or ''),
        'shipment_status': str(getattr(shipment, 'shipment_status', '') or ''),
        'trip_type': str(getattr(shipment, 'trip_type', '') or ''),
    }


def build_shipment_card(
    shipment: Any,
    *,
    tenant_schema: str,
) -> dict[str, Any]:
    """
    Map a shipment to the shipment slice of ``current_job``.

    TODO: Stops, cargo summary, execution stage from operation_runtime.
    """
    _ = tenant_schema
    return build_active_shipment_slice(shipment)
