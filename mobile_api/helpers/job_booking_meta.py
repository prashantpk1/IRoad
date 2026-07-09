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


def _format_date_value(value: Any) -> str:
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value).strip()


def resolve_execution_date(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    movement: Any | None = None,
) -> str:
    """
    Execution date as ``YYYY-MM-DD``.

    Bookings: ``execution_date`` with fallback to ``booking_date``.
    Movements: ``start_time`` date when the job has started, else ``movement_date``.
    """
    resolved_booking = booking
    if resolved_booking is None and shipment is not None:
        resolved_booking = getattr(shipment, 'booking', None)
    if resolved_booking is not None:
        execution = getattr(resolved_booking, 'execution_date', None)
        fallback = getattr(resolved_booking, 'booking_date', None)
        return _format_date_value(execution or fallback)

    if movement is not None:
        start_time = getattr(movement, 'start_time', None)
        if start_time is not None:
            if hasattr(start_time, 'date'):
                return start_time.date().isoformat()
            return _format_date_value(start_time)
        return _format_date_value(getattr(movement, 'movement_date', None))

    return ''


def resolve_execution_time(*, movement: Any | None = None) -> str:
    """
    Local execution clock time for movements after Start Job.

    Returns ``HH:MM:SS`` when ``movement.start_time`` is set; otherwise empty.
    """
    if movement is None:
        return ''
    start_time = getattr(movement, 'start_time', None)
    if start_time is None:
        return ''
    try:
        from django.utils import timezone

        localized = (
            timezone.localtime(start_time)
            if timezone.is_aware(start_time)
            else start_time
        )
        return localized.strftime('%H:%M:%S')
    except Exception:
        if hasattr(start_time, 'strftime'):
            return start_time.strftime('%H:%M:%S')
        return ''
