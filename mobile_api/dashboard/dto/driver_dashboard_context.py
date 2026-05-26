"""
mobile_api/dashboard/dto/driver_dashboard_context.py

In-memory orchestration context for dashboard resolution (not API output).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mobile_api.dashboard.dto.driver_booking_selection import (
    DriverBookingSelectionResult,
)
from mobile_api.dashboard.dto.driver_empty_move_selection import (
    DriverEmptyMoveSelectionResult,
)


@dataclass
class DriverDashboardContext:
    """
    Populated by ``DashboardContextService.resolve_driver_dashboard_context``.

    Holds raw selections and intermediate projections before
    ``DashboardResponseBuilder`` maps to the outward API contract.
    """

    driver: Any
    tenant_schema: str
    user_id: str

    # Raw selections (populated by selectors)
    active_booking: Any | None = None
    active_shipment: Any | None = None
    active_empty_movement: Any | None = None
    booking_selection: DriverBookingSelectionResult | None = None
    empty_move_selection: DriverEmptyMoveSelectionResult | None = None

    # Projections (populated by projection services)
    booking_projection: dict[str, Any] = field(default_factory=dict)
    shipment_projection: dict[str, Any] = field(default_factory=dict)
    movement_projection: dict[str, Any] = field(default_factory=dict)
    workflow_projection: dict[str, Any] = field(default_factory=dict)
    pod_cod_projection: dict[str, Any] = field(default_factory=dict)

    # Summary / metadata
    summary: dict[str, Any] = field(default_factory=dict)
    sync_metadata: dict[str, Any] = field(default_factory=dict)

    # Read-only reconciliation (``dashboard_status_reconciler``)
    reconciliation: dict[str, Any] = field(default_factory=dict)

    # Polling / ETag (``dashboard_etag_service``)
    latest_action_log_id: str = ''
    content_hash: str = ''
    dashboard_etag: str = ''
    poll_not_modified: bool = False

    # Per-request Action Log + reconcile cache (``dashboard_projection_cache``)
    projection_cache: Any | None = None
