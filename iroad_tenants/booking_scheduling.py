"""Booking duplicate prevention — truck / driver / date (PCS §3.8)."""
from __future__ import annotations

from iroad_tenants.booking_status import (
    BOOKING_LINE_OPEN_STATUSES,
    derive_booking_line_status,
)

DB_STATUS_CONFIRMED = 'Confirmed'


def _booking_line_types(booking) -> list[str]:
    if booking is None:
        return []
    if (booking.trip_type or '').strip() == 'Round':
        return ['Outbound', 'Backload']
    return ['Outbound']


def _line_truck_driver_ids(booking, line_type: str):
    if (line_type or '').strip() == 'Backload':
        return booking.booking_line_backload_truck_id, booking.booking_line_backload_driver_id
    return booking.assigned_truck_id, booking.assigned_driver_id


def _booking_line_is_open(booking, line_type: str) -> bool:
    return derive_booking_line_status(booking, line_type) in BOOKING_LINE_OPEN_STATUSES


def _confirmed_bookings_on_date(booking_date, *, exclude_booking_id=None):
    from tenant_workspace.models import TenantBooking

    qs = TenantBooking.objects.filter(
        booking_status=DB_STATUS_CONFIRMED,
        booking_date=booking_date,
    ).select_related(
        'assigned_truck',
        'assigned_driver',
        'booking_line_backload_truck',
        'booking_line_backload_driver',
    )
    if exclude_booking_id:
        qs = qs.exclude(pk=exclude_booking_id)
    return qs


def _truck_blocks_on_booking(booking, truck) -> bool:
    if (booking.booking_status or '').strip() != DB_STATUS_CONFIRMED:
        return False
    truck_id = truck.pk
    for line_type in _booking_line_types(booking):
        line_truck_id, _ = _line_truck_driver_ids(booking, line_type)
        if line_truck_id != truck_id:
            continue
        if _booking_line_is_open(booking, line_type):
            return True
    return False


def _driver_blocks_on_booking(booking, driver) -> bool:
    if (booking.booking_status or '').strip() != DB_STATUS_CONFIRMED:
        return False
    driver_id = driver.pk
    for line_type in _booking_line_types(booking):
        _, line_driver_id = _line_truck_driver_ids(booking, line_type)
        if line_driver_id != driver_id:
            continue
        if _booking_line_is_open(booking, line_type):
            return True
    return False


def _pair_blocks_on_booking(booking, truck, driver) -> bool:
    if (booking.booking_status or '').strip() != DB_STATUS_CONFIRMED:
        return False
    truck_id = truck.pk
    driver_id = driver.pk
    for line_type in _booking_line_types(booking):
        line_truck_id, line_driver_id = _line_truck_driver_ids(booking, line_type)
        if line_truck_id != truck_id or line_driver_id != driver_id:
            continue
        if _booking_line_is_open(booking, line_type):
            return True
    return False


def _truck_conflict(booking_date, truck, *, exclude_booking_id=None) -> bool:
    for booking in _confirmed_bookings_on_date(
        booking_date,
        exclude_booking_id=exclude_booking_id,
    ):
        if _truck_blocks_on_booking(booking, truck):
            return True
    return False


def _driver_conflict(booking_date, driver, *, exclude_booking_id=None) -> bool:
    for booking in _confirmed_bookings_on_date(
        booking_date,
        exclude_booking_id=exclude_booking_id,
    ):
        if _driver_blocks_on_booking(booking, driver):
            return True
    return False


def _pair_conflict(booking_date, truck, driver, *, exclude_booking_id=None) -> bool:
    for booking in _confirmed_bookings_on_date(
        booking_date,
        exclude_booking_id=exclude_booking_id,
    ):
        if _pair_blocks_on_booking(booking, truck, driver):
            return True
    return False


def scheduling_conflict_messages(
    *,
    booking_date,
    truck=None,
    driver=None,
    backload_truck=None,
    backload_driver=None,
    exclude_booking_id=None,
) -> list[str]:
    """
    PCS §3.8.1 duplicate prevention on confirm:
    - same driver + same date
    - same truck + same date
    - same truck and driver + same date
    """
    if booking_date is None:
        return []

    messages: list[str] = []
    lines = [
        (truck, driver, 1, 'Outbound'),
        (backload_truck, backload_driver, 2, 'Backload'),
    ]
    for line_truck, line_driver, _line_no, line_label in lines:
        if line_truck and _truck_conflict(
            booking_date,
            line_truck,
            exclude_booking_id=exclude_booking_id,
        ):
            code = getattr(line_truck, 'truck_code', '') or str(line_truck.pk)
            messages.append(
                f'{line_label} line: Truck {code} is already assigned on this booking date.'
            )
        if line_driver and _driver_conflict(
            booking_date,
            line_driver,
            exclude_booking_id=exclude_booking_id,
        ):
            code = getattr(line_driver, 'driver_code', '') or str(line_driver.pk)
            messages.append(
                f'{line_label} line: Driver {code} is already assigned on this booking date.'
            )
        if (
            line_truck
            and line_driver
            and _pair_conflict(
                booking_date,
                line_truck,
                line_driver,
                exclude_booking_id=exclude_booking_id,
            )
        ):
            truck_code = getattr(line_truck, 'truck_code', '') or str(line_truck.pk)
            driver_code = getattr(line_driver, 'driver_code', '') or str(line_driver.pk)
            messages.append(
                f'Duplicate assignment on {line_label} line: truck {truck_code} and '
                f'driver {driver_code} on this booking date.'
            )
    return messages


def scheduling_conflict_exists(**kwargs) -> bool:
    return bool(scheduling_conflict_messages(**kwargs))
