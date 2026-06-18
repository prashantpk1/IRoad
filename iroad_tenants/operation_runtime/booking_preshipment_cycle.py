"""
Backload preshipment cycle scoping for booking-only actions (A1–A4).

When a round-trip outbound leg is execution-complete but the backload shipment
row does not exist yet, preshipment checks must ignore the outbound cycle.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from tenant_workspace.models import TenantBooking, TenantOperationActionLog, TenantShipment

_EXECUTION_COMPLETE = frozenset(
    {
        TenantShipment.ShipmentStatus.DELIVERED,
        TenantShipment.ShipmentStatus.CLOSED,
    },
)

_LINE_ORDER = {'outbound': 0, 'inbound': 1, 'backload': 2}


def _norm_line(value: str | None) -> str:
    return (value or '').strip().casefold()


def _norm_status(shipment: Any) -> str:
    return (getattr(shipment, 'shipment_status', None) or '').strip()


def _norm_trip(booking: Any) -> str:
    return (getattr(booking, 'trip_type', None) or '').strip().casefold()


def _is_execution_complete(shipment: Any) -> bool:
    return _norm_status(shipment) in _EXECUTION_COMPLETE


def _countable_shipments(booking: Any) -> list[Any]:
    if booking is None:
        return []
    try:
        rows = list(booking.shipments.all())
    except Exception:
        rows = list(getattr(booking, 'shipments', []) or [])
    return [
        s
        for s in rows
        if _norm_status(s) != TenantShipment.ShipmentStatus.CANCELLED
    ]


def _shipment_sort_key(shipment: Any) -> tuple:
    line_rank = _LINE_ORDER.get(_norm_line(getattr(shipment, 'booking_item_type', None)), 99)
    return (
        int(getattr(shipment, 'shipment_sequence', 0) or 0),
        line_rank,
        str(getattr(shipment, 'shipment_no', '') or ''),
    )


def _sorted_shipments(booking: Any) -> list[Any]:
    return sorted(_countable_shipments(booking), key=_shipment_sort_key)


def _has_secondary_shipment_row(booking: Any) -> bool:
    return any(
        _norm_line(getattr(s, 'booking_item_type', None)) in {'backload', 'inbound'}
        for s in _countable_shipments(booking)
    )


def _primary_outbound_legs(booking: Any) -> list[Any]:
    legs = _sorted_shipments(booking)
    for i, shipment in enumerate(legs):
        if _norm_line(getattr(shipment, 'booking_item_type', None)) in {'backload', 'inbound'}:
            return list(legs[:i])
    return list(legs)


def is_backload_leg_pending(booking: Any) -> bool:
    """Round-trip backload planned but no backload/inbound shipment row yet."""
    if booking is None or _norm_trip(booking) != 'round':
        return False
    if _has_secondary_shipment_row(booking):
        return False
    primary = _primary_outbound_legs(booking)
    if not primary:
        return False
    return all(_is_execution_complete(s) for s in primary)


def resolve_preshipment_booking_item_type(
    booking: Any,
    booking_item_type: str = '',
) -> str:
    """
    Preshipment leg label for booking-scoped actions (A1–A4).

    When outbound is execution-complete and backload row is not born yet,
    default to ``Backload`` so outbound preshipment logs do not block A1.
    """
    raw = (booking_item_type or '').strip()
    if raw:
        return raw
    if booking is not None and is_backload_leg_pending(booking):
        return 'Backload'
    return 'Outbound'


def is_backload_preshipment_cycle(booking: Any, booking_item_type: str = '') -> bool:
    """Booking-scoped preshipment is for a fresh backload leg (post-outbound)."""
    if not is_backload_leg_pending(booking):
        return False
    line = _norm_line(resolve_preshipment_booking_item_type(booking, booking_item_type))
    return line in {'backload', 'inbound'}


def outbound_execution_complete_anchor(booking: Any) -> datetime | None:
    """
    Timestamp after which backload preshipment logs count.

    Uses the latest Action Log on the execution-complete primary outbound leg,
    falling back to the shipment ``updated_at``.
    """
    primary = _primary_outbound_legs(booking)
    if not primary:
        return None
    outbound = primary[-1]
    if not _is_execution_complete(outbound):
        return None

    shipment_id = getattr(outbound, 'pk', None) or getattr(outbound, 'shipment_id', None)
    anchor: datetime | None = None
    if shipment_id:
        last_log_date = (
            TenantOperationActionLog.objects.filter(shipment_id=shipment_id)
            .order_by('-log_date', '-created_at')
            .values_list('log_date', flat=True)
            .first()
        )
        if last_log_date is not None:
            anchor = last_log_date

    updated_at = getattr(outbound, 'updated_at', None)
    if anchor is None and updated_at is not None:
        anchor = updated_at

    if anchor is not None and timezone.is_naive(anchor):
        anchor = timezone.make_aware(anchor, timezone.get_current_timezone())
    return anchor


def booking_preshipment_log_in_cycle(
    booking: Any,
    log: Any,
    *,
    booking_item_type: str = '',
) -> bool:
    """Whether ``log`` belongs to the current booking preshipment leg cycle."""
    if booking is None or log is None:
        return False
    log_id = getattr(log, 'log_id', None) or getattr(log, 'pk', None)
    if not log_id:
        return False
    return booking_preshipment_logs_queryset(
        booking,
        booking_item_type=booking_item_type,
    ).filter(log_id=log_id).exists()


def booking_preshipment_logs_queryset(
    booking: Any,
    *,
    booking_item_type: str = '',
    exclude_log_id=None,
):
    """Booking-scoped preshipment logs, optionally scoped to a backload cycle."""
    if booking is None:
        return TenantOperationActionLog.objects.none()

    resolved_item_type = resolve_preshipment_booking_item_type(
        booking,
        booking_item_type,
    )

    qs = TenantOperationActionLog.objects.filter(
        booking_id=getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None),
        shipment__isnull=True,
    ).exclude(operation_action__isnull=True)
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)

    if is_backload_preshipment_cycle(booking, resolved_item_type):
        anchor = outbound_execution_complete_anchor(booking)
        if anchor is None:
            return qs.none()
        qs = qs.filter(log_date__gt=anchor)
    return qs
