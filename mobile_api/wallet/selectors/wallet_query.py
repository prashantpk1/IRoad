"""
mobile_api/wallet/selectors/wallet_query.py

Driver-scoped Driver Treasury Transaction queries (read-only).

IRoute Ch.13:
  - Driver sees only their active wallet rows.
  - Client Collection · Credit = COD cash received (A9).
  - Custody Collection · Debit = cash handed over (transfer out).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.db.models import Q

from iroad_tenants.driver_treasury_ops import ensure_active_driver_treasury
from tenant_workspace.models import DriverTreasuryTransaction

_TXN_SELECT = (
    'driver_treasury',
    'driver_treasury__driver',
    'shipment',
    'shipment__booking',
    'shipment__booking__route',
    'shipment__booking__route__origin_point',
    'shipment__booking__route__destination_point',
    'shipment__client_account',
    'shipment__loading_address',
    'shipment__delivery_address',
    'shipment__truck',
)


@dataclass(frozen=True)
class WalletListFilters:
    """Validated list / filter-preview parameters."""

    shipment_no: str = ''
    transaction_date: date | None = None
    count_only: bool = False


@dataclass
class WalletListPage:
    """Wallet list response (paginated)."""

    summary: dict[str, Any]
    items: list[dict[str, Any]]
    count: int
    results_found: int
    total_records: int = 0
    total_pages: int = 0
    current_page: int = 1
    page_size: int = 10


class WalletQuerySelector:
    """Build driver wallet transaction list (paginated)."""

    @classmethod
    def active_treasury(cls, driver: Any):
        return ensure_active_driver_treasury(driver, auto_create=False)

    @classmethod
    def base_transactions_qs(cls, treasury: Any):
        if treasury is None:
            return DriverTreasuryTransaction.objects.none()
        return (
            DriverTreasuryTransaction.objects.filter(driver_treasury=treasury)
            .select_related(*_TXN_SELECT)
            .order_by('-transaction_date', '-created_at', '-transaction_sequence')
        )

    @classmethod
    def apply_filters(cls, qs, *, filters: WalletListFilters):
        token = (filters.shipment_no or '').strip()
        if token:
            if cls._is_uuid(token):
                qs = qs.filter(shipment_id=token)
            else:
                qs = qs.filter(
                    Q(shipment__shipment_no__icontains=token)
                    | Q(transaction_no__icontains=token)
                )

        if filters.transaction_date is not None:
            qs = qs.filter(transaction_date__date=filters.transaction_date)
        return qs

    @classmethod
    def list_transactions(
        cls,
        driver: Any,
        *,
        filters: WalletListFilters,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[Any | None, list[Any], int]:
        treasury = cls.active_treasury(driver)
        if treasury is None:
            return None, [], 0

        qs = cls.apply_filters(
            cls.base_transactions_qs(treasury),
            filters=filters,
        )
        total = qs.count()
        page = max(1, int(page or 1))
        page_size = max(1, int(page_size or 1))
        offset = (page - 1) * page_size
        rows = list(qs[offset : offset + page_size])
        return treasury, rows, total

    @classmethod
    def get_transaction_for_driver(
        cls,
        driver: Any,
        transaction_ref: str,
    ) -> tuple[Any | None, Any | None]:
        """Resolve one transaction by UUID or transaction_no for this driver's wallet."""
        treasury = cls.active_treasury(driver)
        if treasury is None:
            return None, None

        token = (transaction_ref or '').strip()
        if not token:
            return treasury, None

        qs = cls.base_transactions_qs(treasury)
        if cls._is_uuid(token):
            txn = qs.filter(pk=token).first()
        else:
            txn = qs.filter(transaction_no__iexact=token).first()
        return treasury, txn

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except (TypeError, ValueError, AttributeError):
            return False
