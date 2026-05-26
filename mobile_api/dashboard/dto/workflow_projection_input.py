"""
mobile_api/dashboard/dto/workflow_projection_input.py

Inputs for read-only dashboard workflow projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkflowProjectionInput:
    """Entity context passed to ``build_workflow_projection``."""

    request: Any | None = None
    booking: Any | None = None
    shipment: Any | None = None
    movement: Any | None = None
    booking_item_type: str = ''
    job_type: str = ''
    job_id: str = ''
    job_no: str = ''
