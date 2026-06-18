"""
mobile_api/dashboard/dto/driver_booking_selection.py

Result of ``select_current_driver_booking`` — booking row + derived shipment state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DriverBookingSelectionResult:
    """Current driver job (one booking) with derived shipment pointers."""

    booking: Any
    active_shipment: Any | None
    next_executable_shipment: Any | None
    shipments: list[Any] = field(default_factory=list)
    shipments_total: int = 0
    shipments_execution_completed: int = 0
    shipments_business_completed: int = 0
    execution_progress_percentage: int = 0
    business_progress_percentage: int = 0
    # Legacy aliases — execution metrics (mobile sequencing UX).
    shipments_completed: int = 0
    progress_percentage: int = 0
    booking_execution_stage: str = ''
    is_backload_bootstrap: bool = False
