"""Booking status impacts from operation actions."""

from __future__ import annotations

from tenant_workspace.models import TenantBooking


def apply_booking_status_impact(booking, raw_impact) -> None:
    if booking is None:
        return
    token = (raw_impact or '').strip().lower()
    if not token:
        return
    if token in {'draft'}:
        if booking.booking_status != TenantBooking.Status.CANCELLED:
            booking.booking_status = TenantBooking.Status.DRAFT
            booking.save(update_fields=['booking_status', 'updated_at'])
    elif token in {'confirmed', 'in_progress', 'completed', 'active'}:
        if booking.booking_status == TenantBooking.Status.DRAFT:
            booking.booking_status = TenantBooking.Status.CONFIRMED
            booking.save(update_fields=['booking_status', 'updated_at'])
