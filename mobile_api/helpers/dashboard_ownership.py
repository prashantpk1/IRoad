"""
mobile_api/helpers/dashboard_ownership.py

Bulk driver ownership scope for O(1) sanitization (no per-row DB exists).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from mobile_api.helpers.dashboard_aggregations import driver_shipment_scope_pk_list
from mobile_api.helpers.operational_status import driver_movement_scope_q


def _normalize_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value).strip()))
    except (TypeError, ValueError):
        return None


@dataclass
class DriverOwnershipScope:
    """Preloaded shipment/movement PK sets for in-memory ownership checks."""

    shipment_ids: frozenset[str]
    movement_ids: frozenset[str]

    def owns_shipment(self, shipment_id: str | None) -> bool:
        sid = _normalize_uuid(shipment_id)
        return bool(sid and sid in self.shipment_ids)

    def owns_movement(self, movement_id: str | None) -> bool:
        mid = _normalize_uuid(movement_id)
        return bool(mid and mid in self.movement_ids)


def preload_driver_ownership_scope(driver) -> DriverOwnershipScope:
    """
    Two queryset scans (shipments PK list + movements PK list) per request.
    """
    from tenant_workspace.models import TenantTruckMovementLog

    shipment_ids = frozenset(
        str(pk) for pk in driver_shipment_scope_pk_list(driver)
    )
    movement_ids = frozenset(
        str(pk)
        for pk in TenantTruckMovementLog.objects.filter(
            driver_movement_scope_q(driver),
        ).values_list('pk', flat=True)[: _movement_cap()]
    )
    return DriverOwnershipScope(
        shipment_ids=shipment_ids,
        movement_ids=movement_ids,
    )


def _movement_cap() -> int:
    return int(
        getattr(settings, 'MOBILE_API_DASHBOARD_MOVEMENT_SCOPE_PK_CAP', 500) or 500
    )
