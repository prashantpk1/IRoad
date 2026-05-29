"""
mobile_api/helpers/job_booking_meta.py

Client + execution date fields for mobile job/dashboard read APIs.
"""
from __future__ import annotations

from typing import Any


def _localized_client_label(
    client: Any,
    *,
    request: Any | None = None,
) -> str:
    english = (
        getattr(client, 'display_name', '')
        or getattr(client, 'name_english', '')
        or ''
    ).strip()
    arabic = (getattr(client, 'name_arabic', '') or '').strip()
    if request is not None:
        try:
            from mobile_api.helpers.i18n import get_localized_value

            return (
                get_localized_value(request, english, arabic) or english or arabic
            )
        except Exception:
            pass
    return english or arabic


def resolve_client_name(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    request: Any | None = None,
) -> str:
    """Client display name from shipment or booking ``client_account`` FK."""
    client = None
    if shipment is not None:
        client = getattr(shipment, 'client_account', None)
    if client is None and booking is not None:
        client = getattr(booking, 'client_account', None)
    if client is None:
        return ''
    return _localized_client_label(client, request=request)


def resolve_execution_date(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
) -> str:
    """
    Booking execution date as ``YYYY-MM-DD``.

    Falls back to ``booking_date`` when ``execution_date`` is unset.
    """
    resolved_booking = booking
    if resolved_booking is None and shipment is not None:
        resolved_booking = getattr(shipment, 'booking', None)
    if resolved_booking is None:
        return ''
    execution = getattr(resolved_booking, 'execution_date', None)
    fallback = getattr(resolved_booking, 'booking_date', None)
    value = execution or fallback
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value).strip()
