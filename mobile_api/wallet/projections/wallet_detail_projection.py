"""
mobile_api/wallet/projections/wallet_detail_projection.py

Transaction Details screen — read-only (Ch.13 · driver wallet view).
"""
from __future__ import annotations

from typing import Any

from mobile_api.history.projections.history_card_projection import (
    _client_name,
    build_history_card,
    resolve_job_date,
)
from mobile_api.wallet.projections.wallet_card_projection import (
    build_wallet_transaction_card,
    transaction_type_label,
)
from mobile_api.wallet.constants import WALLET_DEFAULT_CURRENCY


def build_wallet_transaction_detail(
    txn: Any,
    *,
    currency: str | None = None,
) -> dict[str, Any]:
    """Full Transaction Details payload."""
    cur = (currency or WALLET_DEFAULT_CURRENCY or 'SAR').strip() or 'SAR'
    card = build_wallet_transaction_card(txn, currency=cur)
    shipment = getattr(txn, 'shipment', None)
    booking = getattr(shipment, 'booking', None) if shipment is not None else None

    summary = {
        'transaction_id': card['transaction_id'],
        'transaction_no': card['transaction_no'],
        'transaction_type_label': transaction_type_label(txn),
        'amount': card['amount'],
        'currency': cur,
        'transaction_date': card['transaction_date'],
        'transaction_date_display': card['transaction_date_display'],
        'cash_flow': card['cash_flow'],
        'read_only': True,
    }

    shipment_card: dict[str, Any] = {}
    if shipment is not None:
        shipment_card = build_history_card(shipment, request=None)
        job_date = resolve_job_date(shipment, booking)
        route = shipment_card.get('route') or {}
        order_type = str(shipment_card.get('order_type') or '').strip()
        shipment_card.update(
            {
                'transaction_type_label': card['transaction_type_label'],
                'origin': {
                    'city': str(route.get('route_display_start') or route.get('origin_city') or ''),
                    'address': str(route.get('from_location') or route.get('route_display_start') or ''),
                },
                'destination': {
                    'city': str(route.get('route_display_end') or route.get('destination_city') or ''),
                    'address': str(route.get('to_location') or route.get('route_display_end') or ''),
                },
                'client_name': _client_name(shipment, booking),
                'shipment_date': (
                    getattr(shipment, 'shipment_date', None).isoformat()
                    if getattr(shipment, 'shipment_date', None) is not None
                    else ''
                ),
                'job_date': job_date.isoformat() if job_date else '',
            }
        )
        if order_type:
            shipment_card['transaction_type'] = order_type

    return {
        'summary': summary,
        'transaction': card,
        'shipment': shipment_card,
        'description': str(getattr(txn, 'description', '') or ''),
        'wallet_projection_version': '1',
        'read_only': True,
    }
