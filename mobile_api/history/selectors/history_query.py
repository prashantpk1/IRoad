"""
mobile_api/history/selectors/history_query.py

Driver-scoped queryset for completed shipment history (read-only).

Operational rules (IRoute §14.7.1):
  - History = terminal legs only (``Closed`` or ``Cancelled``).
  - Reverse chronological by job/shipment date.
  - Driver must own the shipment leg (same rules as Job Detail).
  - Paginated via ``page`` and ``page_size`` query params.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q

from mobile_api.history.constants import HISTORY_LIST_MAX_RESULTS
from mobile_api.job_detail.guards.ownership import driver_owns_shipment_leg, driver_pk
from tenant_workspace.models import TenantShipment

_HISTORY_TERMINAL_STATUSES = (
    TenantShipment.ShipmentStatus.CLOSED,
    TenantShipment.ShipmentStatus.CANCELLED,
)

_SHIPMENT_SELECT = (
    'booking',
    'booking__assigned_driver',
    'booking__booking_line_backload_driver',
    'booking__assigned_truck',
    'booking__booking_line_backload_truck',
    'booking__loading_address',
    'booking__delivery_address',
    'booking__route',
    'booking__route__origin_point',
    'booking__route__destination_point',
    'client_account',
    'loading_address',
    'delivery_address',
    'driver',
    'cargo',
    'truck',
)


@dataclass(frozen=True)
class HistoryListFilters:
    """Validated list / filter-preview parameters."""

    shipment_no: str = ''
    job_date: date | None = None
    count_only: bool = False


@dataclass
class HistoryListPage:
    """History list response (paginated)."""

    items: list[dict[str, Any]]
    count: int
    results_found: int
    total_records: int = 0
    total_pages: int = 0
    current_page: int = 1
    page_size: int = 10


class HistoryQuerySelector:
    """Build driver history shipment list (no pagination)."""

    @classmethod
    def driver_history_base_qs(cls, driver: Any):
        """Terminal shipments assigned to this driver (ORM pre-filter)."""
        pk = driver_pk(driver)
        if pk is None:
            return TenantShipment.objects.none()

        return (
            TenantShipment.objects.filter(
                shipment_status__in=_HISTORY_TERMINAL_STATUSES,
            )
            .filter(
                Q(driver_id=pk)
                | Q(booking__assigned_driver_id=pk)
                | Q(booking__booking_line_backload_driver_id=pk)
            )
            .select_related(*_SHIPMENT_SELECT)
            .distinct()
        )

    @classmethod
    def apply_filters(
        cls,
        qs,
        *,
        filters: HistoryListFilters,
    ):
        token = (filters.shipment_no or '').strip()
        if token:
            if cls._is_uuid(token):
                qs = qs.filter(pk=token)
            else:
                qs = qs.filter(shipment_no__icontains=token)

        if filters.job_date is not None:
            qs = qs.filter(
                Q(shipment_date=filters.job_date)
                | Q(booking__execution_date=filters.job_date)
                | Q(booking__booking_date=filters.job_date)
            )
        return qs

    @classmethod
    def filter_owned_terminal_shipments(
        cls,
        driver: Any,
        *,
        filters: HistoryListFilters,
        max_results: int | None = None,
    ) -> list[Any]:
        """
        Return owned terminal shipments matching filters, newest first.

        Post-filters with ``driver_owns_shipment_leg`` for precise leg ownership.
        """
        cap = max_results if max_results is not None else HISTORY_LIST_MAX_RESULTS
        cap = max(1, int(cap))

        qs = cls.apply_filters(
            cls.driver_history_base_qs(driver),
            filters=filters,
        )
        qs = qs.order_by('-shipment_date', '-updated_at', '-shipment_sequence')

        owned: list[Any] = []
        for shipment in qs.iterator(chunk_size=200):
            booking = getattr(shipment, 'booking', None)
            if not driver_owns_shipment_leg(driver, booking, shipment):
                continue
            owned.append(shipment)
            if len(owned) >= cap:
                break
        return owned

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except (TypeError, ValueError, AttributeError):
            return False
