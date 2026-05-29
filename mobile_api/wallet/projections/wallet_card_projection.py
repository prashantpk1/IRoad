"""
mobile_api/wallet/projections/wallet_card_projection.py

Wallet transaction list card — My Wallet recent transactions UI.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from mobile_api.history.projections.history_card_projection import (
    final_state_labels,
    payment_method_tag,
    resolve_job_date,
)
from mobile_api.wallet.constants import WALLET_DEFAULT_CURRENCY
from tenant_workspace.models import DriverTreasuryTransaction


def _decimal_amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal('0')


def transaction_type_label(txn: Any) -> str:
    """
    UI label for the transaction header.

    Ch.13: Client Collection (Debit) = cash received; Custody Collection (Credit) = handover.
    """
    category = str(getattr(txn, 'transaction_category', '') or '').strip()
    txn_type = str(getattr(txn, 'transaction_type', '') or '').strip()

    if category == DriverTreasuryTransaction.TransactionCategory.CLIENT_COLLECTION:
        if txn_type == DriverTreasuryTransaction.TransactionType.DEBIT:
            return 'Received Amount'
        return 'Client Collection'

    if category == DriverTreasuryTransaction.TransactionCategory.CUSTODY_COLLECTION:
        return 'Transferred Out'

    if txn_type == DriverTreasuryTransaction.TransactionType.DEBIT:
        return 'Received Amount'
    return 'Transferred Out'


def cash_flow_direction(txn: Any) -> str:
    """``in`` increases driver wallet balance; ``out`` decreases it."""
    txn_type = str(getattr(txn, 'transaction_type', '') or '').strip()
    if txn_type == DriverTreasuryTransaction.TransactionType.DEBIT:
        return 'in'
    return 'out'


def format_transaction_date(txn: Any) -> str:
    txn_date = getattr(txn, 'transaction_date', None)
    if txn_date is None:
        return ''
    try:
        return txn_date.strftime('%d %b %Y')
    except Exception:
        return str(txn_date)


def format_transaction_date_iso(txn: Any) -> str:
    txn_date = getattr(txn, 'transaction_date', None)
    if txn_date is None:
        return ''
    if hasattr(txn_date, 'date'):
        return txn_date.date().isoformat()
    return str(txn_date)


def build_wallet_summary(
    treasury: Any | None,
    *,
    currency: str | None = None,
) -> dict[str, Any]:
    """Top-of-screen Total Cash Collected card."""
    cur = (currency or WALLET_DEFAULT_CURRENCY or 'SAR').strip() or 'SAR'
    if treasury is None:
        return {
            'treasury_id': '',
            'treasury_code': '',
            'total_cash_collected': '0.00',
            'currency': cur,
            'sync_status': 'synced',
            'read_only': True,
        }

    balance = _decimal_amount(getattr(treasury, 'current_balance', 0))
    return {
        'treasury_id': str(getattr(treasury, 'treasury_id', '') or treasury.pk or ''),
        'treasury_code': str(getattr(treasury, 'treasury_code', '') or ''),
        'total_cash_collected': f'{balance:.2f}',
        'currency': cur,
        'sync_status': 'synced',
        'read_only': True,
    }


def build_wallet_transaction_card(txn: Any, *, currency: str | None = None) -> dict[str, Any]:
    """One row in Recent Transactions."""
    cur = (currency or WALLET_DEFAULT_CURRENCY or 'SAR').strip() or 'SAR'
    amount = _decimal_amount(getattr(txn, 'amount', 0))
    shipment = getattr(txn, 'shipment', None)
    booking = getattr(shipment, 'booking', None) if shipment is not None else None
    job_date = resolve_job_date(shipment, booking) if shipment is not None else None

    display_status = ''
    if shipment is not None:
        display_status, _ = final_state_labels(shipment)

    shipment_no = str(getattr(shipment, 'shipment_no', '') or '') if shipment else ''
    booking_no = str(getattr(booking, 'booking_no', '') or '') if booking else ''

    return {
        'transaction_id': str(getattr(txn, 'transaction_id', '') or txn.pk or ''),
        'transaction_no': str(getattr(txn, 'transaction_no', '') or ''),
        'booking_no': booking_no,
        'shipment_id': (
            str(getattr(shipment, 'shipment_id', '') or getattr(shipment, 'pk', '') or '')
            if shipment is not None
            else ''
        ),
        'shipment_no': shipment_no,
        'amount': f'{amount:.2f}',
        'currency': cur,
        'cash_flow': cash_flow_direction(txn),
        'transaction_type_label': transaction_type_label(txn),
        'transaction_category': str(getattr(txn, 'transaction_category', '') or ''),
        'transaction_type': str(getattr(txn, 'transaction_type', '') or ''),
        'transaction_date': format_transaction_date_iso(txn),
        'transaction_date_display': format_transaction_date(txn),
        'payment_method': payment_method_tag(shipment, booking) if shipment else '',
        'shipment_status': display_status,
        'job_date': job_date.isoformat() if job_date else '',
        'read_only': True,
    }
