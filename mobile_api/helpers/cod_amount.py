"""
mobile_api/helpers/cod_amount.py

Resolve expected COD collection amount for driver-facing APIs (doc §14.5.2).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from mobile_api.helpers.order_type import ORDER_TYPE_COD, resolve_order_type_text

_DEFAULT_CURRENCY = 'SAR'


def resolve_expected_cod_amount(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
) -> Decimal:
    """
    Expected cash to collect: shipment ``cod_amount``, else booking line COD.
    """
    if shipment is not None:
        raw = getattr(shipment, 'cod_amount', None)
        if raw is not None:
            amount = Decimal(str(raw))
            if amount > 0:
                return amount

    if booking is not None:
        line_type = ''
        if shipment is not None:
            line_type = (getattr(shipment, 'booking_item_type', None) or '').strip().lower()
        if line_type in {'backload', 'inbound'}:
            raw = getattr(booking, 'booking_line_backload_cod_amount', None)
        else:
            raw = getattr(booking, 'booking_line_cod_amount', None)
        if raw is not None:
            amount = Decimal(str(raw))
            if amount > 0:
                return amount

    return Decimal('0')


def build_cod_payment_display(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
) -> dict[str, Any]:
    """
    Driver Collect Payment fields: amount due from booking line / shipment COD.
    """
    if resolve_order_type_text(shipment=shipment, booking=booking) != ORDER_TYPE_COD:
        return {}

    amount = resolve_expected_cod_amount(shipment=shipment, booking=booking)
    if amount <= 0:
        return {}

    text = format(amount, 'f')
    return {
        'expected_cod_amount': text,
        'amount_due': text,
        'cod_amount': text,
        'currency': _DEFAULT_CURRENCY,
        'field_configuration': build_payment_screen_field_configuration(),
        'collection_rules': build_payment_collection_rules(minimum_amount=amount),
    }


def build_payment_screen_field_configuration() -> dict[str, bool]:
    """Driver Collect Payment screen — comment and attachment are optional."""
    return {
        'comment_required': False,
        'attachment_required': False,
    }


def build_payment_collection_rules(*, minimum_amount: Decimal) -> dict[str, Any]:
    """Driver may collect the exact due amount or higher; never less."""
    minimum = Decimal(str(minimum_amount or 0))
    return {
        'minimum_amount': format(minimum, 'f'),
        'allow_over_collection': True,
        'block_under_collection': True,
    }
