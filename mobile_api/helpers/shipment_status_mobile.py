"""
mobile_api/helpers/shipment_status_mobile.py

Driver-app shipment status: Digital POD → POD Submitted after digital evidence;
Hard POD → POD Submitted only after hard-copy custody completes.
"""
from __future__ import annotations

from typing import Any

from tenant_workspace.models import TenantShipment

from iroad_tenants.operation_runtime.latest_state import (
    clamp_shipment_status_cache_for_hard_pod,
    repair_shipment_status_before_hard_pod_promotion,
)


def mobile_effective_shipment_status(
    shipment: Any | None,
    status: str | None,
    *,
    repair_column: bool = False,
) -> str:
    """
    Clamp premature POD Submitted on Hard POD legs for mobile workflow + API.

    When ``repair_column`` is True, persist At Delivery for legacy rows stuck at
    POD Submitted/Delivered before hard-copy confirmation (promotion path).
    """
    raw = (status or '').strip()
    if not raw or shipment is None:
        return raw
    if repair_column and raw in {
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.DELIVERED,
    }:
        repair_shipment_status_before_hard_pod_promotion(shipment)
        raw = (getattr(shipment, 'shipment_status', None) or '').strip() or raw
    clamped = clamp_shipment_status_cache_for_hard_pod(shipment, raw)
    return (clamped or raw).strip()
