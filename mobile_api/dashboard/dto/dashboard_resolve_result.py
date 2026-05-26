"""
mobile_api/dashboard/dto/dashboard_resolve_result.py

Result of dashboard resolution including optional 304 / ETag metadata.
"""
from __future__ import annotations

from dataclasses import dataclass

from mobile_api.dashboard.dto.driver_dashboard_context import (
    DriverDashboardContext,
)


@dataclass
class DashboardResolveResult:
    """Orchestration output for ``DashboardAPIView``."""

    context: DriverDashboardContext
    etag: str = ''
    not_modified: bool = False
