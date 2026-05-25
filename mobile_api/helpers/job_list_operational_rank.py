"""
mobile_api/helpers/job_list_operational_rank.py

Indexed operational rank for shipment ``priority_desc`` list sorting.
"""
from __future__ import annotations

from tenant_workspace.models import TenantShipment

from mobile_api.helpers.operational_status import SHIPMENT_ACTIVE_STATUSES

RANK_POD = 0
RANK_COD = 1
RANK_ACTIVE = 2
RANK_DEFAULT = 10


def compute_shipment_operational_rank(shipment) -> int:
    """
    Deterministic rank for mobile job list priority sort (lower = higher priority).
    """
    status = (getattr(shipment, 'shipment_status', None) or '').strip()
    if status not in SHIPMENT_ACTIVE_STATUSES:
        return RANK_DEFAULT
    pod = (getattr(shipment, 'pod_status', None) or '').strip()
    if pod == TenantShipment.PodStatus.PENDING:
        return RANK_POD
    collection = (getattr(shipment, 'collection_status', None) or '').strip()
    order_type = (getattr(shipment, 'order_type', None) or '').strip().upper()
    cod_amount = getattr(shipment, 'cod_amount', None) or 0
    if collection == TenantShipment.CollectionStatus.PENDING and (
        order_type == 'COD' or cod_amount > 0
    ):
        return RANK_COD
    return RANK_ACTIVE


def apply_operational_rank_on_save(shipment) -> None:
    """Persist rank on shipment before save (when field exists)."""
    if hasattr(shipment, 'mobile_operational_rank'):
        shipment.mobile_operational_rank = compute_shipment_operational_rank(shipment)
