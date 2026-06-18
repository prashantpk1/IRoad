"""Booking status impacts from operation actions (PCS §9.3)."""

from __future__ import annotations

from iroad_tenants.status_impact_resolution import resolve_booking_status_impact
from tenant_workspace.models import TenantBooking


def apply_booking_status_impact(booking, raw_impact) -> None:
    """Apply booking status impact when an operation action occurs."""
    if booking is None:
        return

    impact_key = resolve_booking_status_impact(raw_impact)
    if not impact_key:
        return

    if impact_key == 'draft':
        if booking.booking_status != TenantBooking.Status.CANCELLED:
            booking.booking_status = TenantBooking.Status.DRAFT
            booking.save(update_fields=['booking_status', 'updated_at'])
        return

    if impact_key == 'cancelled':
        if booking.booking_status != TenantBooking.Status.CANCELLED:
            booking.booking_status = TenantBooking.Status.CANCELLED
            booking.save(update_fields=['booking_status', 'updated_at'])
        return

    if booking.booking_status == TenantBooking.Status.DRAFT:
        booking.booking_status = TenantBooking.Status.CONFIRMED
        booking.save(update_fields=['booking_status', 'updated_at'])
