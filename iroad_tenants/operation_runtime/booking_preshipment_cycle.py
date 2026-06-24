"""
Backload preshipment cycle scoping for booking-only actions (A1–A4).

When a round-trip outbound leg is execution-complete or cancelled but the backload
shipment row does not exist yet, preshipment checks must ignore the outbound cycle.
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


def _all_shipments(booking: Any) -> list[Any]:
    if booking is None:
        return []
    if hasattr(booking, 'shipments'):
        try:
            rows = booking.shipments.all()
            if isinstance(rows, (list, tuple)):
                return list(rows)
            return list(rows)
        except Exception:
            pass
    booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
    if not booking_id:
        return []
    return list(
        TenantShipment.objects.filter(booking_id=booking_id).order_by(
            'shipment_sequence',
            'shipment_no',
        )
    )


def _outbound_shipments(booking: Any) -> list[Any]:
    return [
        s
        for s in _all_shipments(booking)
        if _norm_line(getattr(s, 'booking_item_type', None)) == 'outbound'
    ]


def _is_cancelled(shipment: Any) -> bool:
    return _norm_status(shipment) == TenantShipment.ShipmentStatus.CANCELLED


def _outbound_primary_resolved(booking: Any) -> bool:
    """
    Outbound leg is finished (closed/delivered) or cancelled — backload may start.
    """
    outbound_rows = _outbound_shipments(booking)
    if not outbound_rows:
        return False
    return all(
        _is_cancelled(s) or _is_execution_complete(s)
        for s in outbound_rows
    )


def _anchor_from_shipment(shipment: Any) -> datetime | None:
    shipment_id = getattr(shipment, 'pk', None) or getattr(shipment, 'shipment_id', None)
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

        movement_log_date = (
            TenantOperationActionLog.objects.filter(
                truck_movement__shipment_id=shipment_id,
            )
            .order_by('-log_date', '-created_at')
            .values_list('log_date', flat=True)
            .first()
        )
        if movement_log_date is not None and (
            anchor is None or movement_log_date > anchor
        ):
            anchor = movement_log_date

    updated_at = getattr(shipment, 'updated_at', None)
    if anchor is None and updated_at is not None:
        anchor = updated_at

    if anchor is not None and timezone.is_naive(anchor):
        anchor = timezone.make_aware(anchor, timezone.get_current_timezone())
    return anchor


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
    if _outbound_primary_resolved(booking):
        return True
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

    When outbound is execution-complete/cancelled and backload row is not born yet,
    default to ``Backload`` so outbound preshipment logs do not block A1 or mis-route A4.
    """
    raw = (booking_item_type or '').strip()
    if booking is not None and is_backload_leg_pending(booking):
        if not raw or _norm_line(raw) == 'outbound':
            return 'Backload'
    if raw:
        return raw
    if booking is not None and is_backload_leg_pending(booking):
        return 'Backload'
    return 'Outbound'


def is_backload_preshipment_cycle(booking: Any, booking_item_type: str = '') -> bool:
    """
    Booking-scoped preshipment is for the backload/inbound leg (post-outbound).

    Applies while the backload row is still pending *and* after it exists so outbound
    A2/A3 logs are not reused on the backload shipment timeline.
    """
    if booking is None or _norm_trip(booking) != 'round':
        return False
    line = _norm_line(resolve_preshipment_booking_item_type(booking, booking_item_type))
    if line not in {'backload', 'inbound'}:
        return False
    return _outbound_primary_resolved(booking)


def _resolved_outbound_shipment(booking: Any) -> Any | None:
    """Primary outbound shipment row used for backload cycle boundaries."""
    primary = _primary_outbound_legs(booking)
    if primary:
        return primary[-1]
    outbound_rows = sorted(_outbound_shipments(booking), key=_shipment_sort_key)
    return outbound_rows[-1] if outbound_rows else None


def outbound_shipment_birth_anchor(booking: Any) -> datetime | None:
    """
    When the outbound shipment row was born (Confirm Loaded / portal create).

    Booking-scoped preshipment logs before this instant belong to the outbound
    cycle only — they must not satisfy backload Start Job / Pickup / Loading.
    """
    outbound = _resolved_outbound_shipment(booking)
    if outbound is None:
        return None
    birth_at = getattr(outbound, 'created_at', None)
    if birth_at is None:
        return None
    if timezone.is_naive(birth_at):
        birth_at = timezone.make_aware(birth_at, timezone.get_current_timezone())
    return birth_at


def outbound_execution_complete_anchor(booking: Any) -> datetime | None:
    """
    Timestamp after which backload preshipment logs count.

    Uses the latest Action Log on the execution-complete or cancelled outbound leg,
    falling back to the shipment ``updated_at``.
    """
    outbound = _resolved_outbound_shipment(booking)
    if outbound is not None and _is_execution_complete(outbound):
        return _anchor_from_shipment(outbound)

    cancelled_outbound = sorted(
        [s for s in _outbound_shipments(booking) if _is_cancelled(s)],
        key=_shipment_sort_key,
    )
    if cancelled_outbound:
        return _anchor_from_shipment(cancelled_outbound[-1])

    return None


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
        birth_at = outbound_shipment_birth_anchor(booking)
        if birth_at is not None:
            # Outbound A1–A3 are always logged before the outbound shipment row exists.
            qs = qs.filter(log_date__gte=birth_at)
    return qs


def scoped_preshipment_action_logs(
    booking: Any,
    *,
    booking_item_type: str = '',
    driver_id=None,
    scan_limit: int = 200,
):
    """
    Booking preshipment logs for mobile timeline/reconcile (respects backload cycle anchor).
    """
    from django.db.models import Q

    if booking is None:
        return TenantOperationActionLog.objects.none()

    resolved = resolve_preshipment_booking_item_type(booking, booking_item_type)
    qs = (
        booking_preshipment_logs_queryset(booking, booking_item_type=resolved)
        .select_related('operation_action', 'driver')
        .order_by('-log_date', '-created_at', '-log_id')
    )
    if driver_id:
        qs = qs.filter(Q(driver_id=driver_id) | Q(driver_id__isnull=True))
    return qs[:scan_limit]
