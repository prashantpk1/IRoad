"""
mobile_api/services/driver_dashboard_build.py

Shared dashboard build state — deduplicates shipment scope and latest-active reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mobile_api.helpers.dashboard_aggregations import driver_shipment_scope_pk_list


@dataclass
class DashboardBuildState:
    """
    Per-request dashboard ORM hints (populated lazily).

    Cuts duplicate shipment scope subqueries and re-fetches of the latest active job.
    """

    driver: Any
    tenant_schema: str
    tenant_profile_id: str | None = None
    request: Any = None
    variant: str = 'full'
    _shipment_scope_pks: list | None = field(default=None, repr=False)
    _latest_active_shipment: Any = field(default=None, repr=False)
    _latest_active_shipment_loaded: bool = field(default=False, repr=False)

    def shipment_scope_pks(self) -> list:
        if self._shipment_scope_pks is None:
            self._shipment_scope_pks = driver_shipment_scope_pk_list(self.driver)
        return self._shipment_scope_pks

    def get_latest_active_shipment(self, *, fetcher):
        """Return cached latest active shipment or call ``fetcher(driver=...)`` once."""
        if self._latest_active_shipment_loaded:
            return self._latest_active_shipment
        self._latest_active_shipment = fetcher(driver=self.driver)
        self._latest_active_shipment_loaded = True
        return self._latest_active_shipment

    def seed_latest_active_shipment(self, shipment) -> None:
        self._latest_active_shipment = shipment
        self._latest_active_shipment_loaded = True
