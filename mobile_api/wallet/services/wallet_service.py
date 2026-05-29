"""
mobile_api/wallet/services/wallet_service.py

Orchestration for driver My Wallet list, filter preview, and transaction detail.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.job_detail.guards.ownership import assert_driver_active
from mobile_api.wallet.constants import WALLET_DEFAULT_CURRENCY
from mobile_api.wallet.exceptions import WalletError
from mobile_api.wallet.projections.wallet_card_projection import (
    build_wallet_summary,
    build_wallet_transaction_card,
)
from mobile_api.wallet.projections.wallet_detail_projection import (
    build_wallet_transaction_detail,
)
from mobile_api.wallet.selectors.wallet_query import (
    WalletListFilters,
    WalletListPage,
    WalletQuerySelector,
)


def parse_wallet_date(raw: str | None) -> date | None:
    """Parse filter date — ISO ``YYYY-MM-DD`` or UI ``DD-MM-YYYY``."""
    token = (raw or '').strip()
    if not token:
        return None

    parsed = parse_date(token)
    if parsed is not None:
        return parsed

    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y'):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue

    raise WalletError(
        str(_('mobile.wallet.invalid_date')),
        code='invalid_date',
        http_status=400,
        message_key='mobile.wallet.invalid_date',
    )


def validate_shipment_no(raw: str | None) -> str:
    token = (raw or '').strip()
    if len(token) > 64:
        raise WalletError(
            str(_('mobile.wallet.shipment_no_too_long')),
            code='validation_failed',
            http_status=400,
            message_key='mobile.validation.failed',
        )
    return token


class WalletService:
    """Driver wallet read APIs."""

    def __init__(self, *, selector: WalletQuerySelector | None = None) -> None:
        self._selector = selector or WalletQuerySelector()

    def list_wallet(
        self,
        driver: Any,
        *,
        tenant_schema: str,
        shipment_no: str = '',
        transaction_date: str | None = None,
        count_only: bool = False,
        currency: str | None = None,
    ) -> WalletListPage:
        schema = (tenant_schema or '').strip()
        if not schema:
            raise WalletError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )

        driver_err = assert_driver_active(driver)
        if driver_err:
            raise WalletError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=403,
                message_key='mobile.auth.driver_inactive',
            )

        filters = WalletListFilters(
            shipment_no=validate_shipment_no(shipment_no),
            transaction_date=parse_wallet_date(transaction_date) if transaction_date else None,
            count_only=bool(count_only),
        )
        cur = (currency or WALLET_DEFAULT_CURRENCY or 'SAR').strip() or 'SAR'

        with schema_context(schema):
            treasury, rows = self._selector.list_transactions(driver, filters=filters)
            results_found = len(rows)
            summary = build_wallet_summary(treasury, currency=cur)

            if filters.count_only:
                return WalletListPage(
                    summary=summary,
                    items=[],
                    count=0,
                    results_found=results_found,
                )

            items = [
                build_wallet_transaction_card(txn, currency=cur)
                for txn in rows
            ]
            return WalletListPage(
                summary=summary,
                items=items,
                count=len(items),
                results_found=results_found,
            )

    def get_transaction_detail(
        self,
        driver: Any,
        transaction_ref: str,
        *,
        tenant_schema: str,
        currency: str | None = None,
    ) -> dict[str, Any]:
        schema = (tenant_schema or '').strip()
        if not schema:
            raise WalletError(
                str(_('mobile.auth.tenant_required')),
                code='tenant_required',
                http_status=400,
                message_key='mobile.auth.tenant_required',
            )

        driver_err = assert_driver_active(driver)
        if driver_err:
            raise WalletError(
                str(_('mobile.auth.driver_inactive')),
                code=driver_err,
                http_status=403,
                message_key='mobile.auth.driver_inactive',
            )

        token = (transaction_ref or '').strip()
        if not token:
            raise WalletError(
                str(_('mobile.wallet.transaction_not_found')),
                code='transaction_not_found',
                http_status=404,
                message_key='mobile.wallet.transaction_not_found',
            )

        cur = (currency or WALLET_DEFAULT_CURRENCY or 'SAR').strip() or 'SAR'

        with schema_context(schema):
            treasury, txn = self._selector.get_transaction_for_driver(driver, token)
            if treasury is None:
                raise WalletError(
                    str(_('mobile.wallet.wallet_not_found')),
                    code='wallet_not_found',
                    http_status=404,
                    message_key='mobile.wallet.wallet_not_found',
                )
            if txn is None:
                raise WalletError(
                    str(_('mobile.wallet.transaction_not_found')),
                    code='transaction_not_found',
                    http_status=404,
                    message_key='mobile.wallet.transaction_not_found',
                )

            return build_wallet_transaction_detail(txn, currency=cur)
