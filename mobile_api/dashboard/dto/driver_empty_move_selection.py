"""
mobile_api/dashboard/dto/driver_empty_move_selection.py

Result of empty-move selection for the driver dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DriverEmptyMoveSelectionResult:
    """Active empty truck movement with derived workflow state."""

    movement: Any
    movement_stage: str = ''
    movement_status: str = ''
    progress_percentage: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
