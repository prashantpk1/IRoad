"""
mobile_api/execution/dto/execute_action_result.py

Orchestrator outcome type (decoupled from service modules).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecuteActionResult:
    """Orchestrator outcome — API payload + HTTP status."""

    payload: dict[str, Any]
    http_status: int = 200
