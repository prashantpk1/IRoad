"""Booking header and line status derivation (PCS §3.4 / Action Master alignment)."""
from __future__ import annotations

from django.utils import timezone

DB_STATUS_DRAFT = 'Draft'
DB_STATUS_CONFIRMED = 'Confirmed'
DB_STATUS_COMPLETED = 'Completed'
DB_STATUS_CANCELLED = 'Cancelled'

BOOKING_HEADER_DRAFT = 'Draft'
BOOKING_HEADER_CONFIRMED = 'Confirmed'
BOOKING_HEADER_IN_PROGRESS = 'In Progress'
BOOKING_HEADER_PARTIALLY_COMPLETED = 'Partially Completed'
BOOKING_HEADER_COMPLETED = 'Completed'
BOOKING_HEADER_CANCELLED = 'Cancelled'

SHIPMENT_STATUS_CANCELLED = 'Cancelled'
SHIPMENT_STATUS_CLOSED = 'Closed'
SHIPMENT_STATUS_DELIVERED = 'Delivered'

# PCS §9.3.1.1 — Operation Action Master "Booking Status Impact" dropdown.
OPERATION_ACTION_BOOKING_STATUS_CHOICES = (
    (BOOKING_HEADER_DRAFT, BOOKING_HEADER_DRAFT),
    (BOOKING_HEADER_CONFIRMED, BOOKING_HEADER_CONFIRMED),
    (BOOKING_HEADER_IN_PROGRESS, BOOKING_HEADER_IN_PROGRESS),
    (BOOKING_HEADER_PARTIALLY_COMPLETED, BOOKING_HEADER_PARTIALLY_COMPLETED),
    (BOOKING_HEADER_COMPLETED, BOOKING_HEADER_COMPLETED),
    (BOOKING_HEADER_CANCELLED, BOOKING_HEADER_CANCELLED),
)

BOOKING_ITEM_DRAFT = 'Draft'
BOOKING_ITEM_CONFIRMED = 'Confirmed'
BOOKING_ITEM_IN_PROGRESS = 'In Progress'
BOOKING_ITEM_COMPLETED = 'Completed'
BOOKING_ITEM_CANCELLED = 'Cancelled'

# Lines that still reserve truck/driver scheduling capacity.
BOOKING_LINE_OPEN_STATUSES = frozenset(
    {
        BOOKING_ITEM_CONFIRMED,
        BOOKING_ITEM_IN_PROGRESS,
    }
)


def display_stored_booking_status(booking_status: str) -> str:
    """Map persisted booking_status to UI label."""
    if booking_status == DB_STATUS_CONFIRMED:
        return BOOKING_HEADER_CONFIRMED
    if booking_status == DB_STATUS_COMPLETED:
        return BOOKING_HEADER_COMPLETED
    return booking_status or DB_STATUS_DRAFT


def booking_has_non_cancelled_shipment(booking) -> bool:
    from tenant_workspace.models import TenantShipment

    if booking is None:
        return False
    return (
        TenantShipment.objects.filter(booking_id=booking.booking_id)
        .exclude(shipment_status=SHIPMENT_STATUS_CANCELLED)
        .exists()
    )


def booking_can_cancel(booking) -> bool:
    if booking is None or booking.booking_status == DB_STATUS_CANCELLED:
        return False
    if booking.booking_status == DB_STATUS_COMPLETED:
        return False
    return not booking_has_non_cancelled_shipment(booking)


def booking_cancel_guard_errors(booking, new_status) -> list[str]:
    """R3: cancel when no active shipment exists (cancelled-only shipments allowed)."""
    if (
        booking is not None
        and new_status == DB_STATUS_CANCELLED
        and booking_has_non_cancelled_shipment(booking)
    ):
        return [
            'Booking cannot be cancelled while a shipment is still active. '
            'Cancel or close shipments first, or use item-level reversal (R2).',
        ]
    return []


def derive_booking_line_status(booking, booking_item_type: str) -> str:
    """
    Booking item status aligned with Action Master vocabulary:
    Draft · Confirmed · In Progress · Completed · Cancelled.
    """
    from tenant_workspace.models import TenantShipment

    if booking is None:
        return BOOKING_ITEM_CONFIRMED
    if booking.booking_status == DB_STATUS_DRAFT:
        return BOOKING_ITEM_DRAFT
    line_type = (booking_item_type or '').strip() or 'Outbound'
    shipments = TenantShipment.objects.filter(
        booking_id=booking.booking_id,
        booking_item_type=line_type,
    )
    if not shipments.exists():
        if booking.booking_status == DB_STATUS_CANCELLED:
            return BOOKING_ITEM_CANCELLED
        return (
            BOOKING_ITEM_CONFIRMED
            if booking.booking_status == DB_STATUS_CONFIRMED
            else BOOKING_ITEM_DRAFT
        )

    terminal = (SHIPMENT_STATUS_CANCELLED, SHIPMENT_STATUS_CLOSED, SHIPMENT_STATUS_DELIVERED)
    if shipments.exclude(shipment_status__in=terminal).exists():
        return BOOKING_ITEM_IN_PROGRESS
    if (
        shipments.filter(shipment_status=SHIPMENT_STATUS_CLOSED).exists()
        or shipments.filter(shipment_status=SHIPMENT_STATUS_DELIVERED).exists()
    ):
        return BOOKING_ITEM_COMPLETED
    if shipments.filter(shipment_status=SHIPMENT_STATUS_CANCELLED).exists():
        return BOOKING_ITEM_CANCELLED
    return (
        BOOKING_ITEM_CONFIRMED
        if booking.booking_status == DB_STATUS_CONFIRMED
        else BOOKING_ITEM_DRAFT
    )


def _booking_line_types(booking) -> list[str]:
    if booking is None:
        return []
    if booking.trip_type == 'Round':
        return ['Outbound', 'Backload']
    if (booking.route_direction or '').strip().lower() == 'reverse':
        return ['Inbound']
    return ['Outbound']


def sync_booking_status_after_item_change(booking, *, save: bool = True) -> bool:
    """
    PCS §3.7.4 — align stored booking_status with derived header status.

    Persists Cancelled when all legs are cancelled, and Completed when every
    non-cancelled leg is business-complete (matches portal UI).
    """
    if booking is None:
        return False
    stored = (booking.booking_status or '').strip()
    if stored in {DB_STATUS_DRAFT, DB_STATUS_CANCELLED}:
        return False
    derived = derive_booking_header_status(booking)
    new_status = None
    if derived == BOOKING_HEADER_CANCELLED:
        new_status = DB_STATUS_CANCELLED
    elif derived == BOOKING_HEADER_COMPLETED:
        new_status = DB_STATUS_COMPLETED
    if new_status is None or stored == new_status:
        return False
    booking.booking_status = new_status
    if save:
        booking.save(update_fields=['booking_status', 'updated_at'])
    return True


def derive_booking_header_status(booking) -> str:
    """
    Derived booking status (PCS §3.4):
    Draft · Confirmed · In Progress · Partially Completed · Completed · Cancelled.
    """
    if booking is None:
        return BOOKING_HEADER_DRAFT
    if booking.booking_status == DB_STATUS_DRAFT:
        return BOOKING_HEADER_DRAFT
    if booking.booking_status == DB_STATUS_CANCELLED:
        return BOOKING_HEADER_CANCELLED
    if booking.booking_status == DB_STATUS_COMPLETED:
        return BOOKING_HEADER_COMPLETED

    line_types = _booking_line_types(booking)
    if not line_types:
        return BOOKING_HEADER_CONFIRMED

    line_states = [derive_booking_line_status(booking, line_type) for line_type in line_types]
    non_cancelled = [state for state in line_states if state != BOOKING_ITEM_CANCELLED]
    if not non_cancelled:
        return BOOKING_HEADER_CANCELLED
    if all(state == BOOKING_ITEM_COMPLETED for state in non_cancelled):
        return BOOKING_HEADER_COMPLETED
    if any(state == BOOKING_ITEM_IN_PROGRESS for state in non_cancelled):
        return BOOKING_HEADER_IN_PROGRESS
    if any(state == BOOKING_ITEM_COMPLETED for state in non_cancelled) and any(
        state == BOOKING_ITEM_CONFIRMED for state in non_cancelled
    ):
        return BOOKING_HEADER_PARTIALLY_COMPLETED
    if all(state == BOOKING_ITEM_CONFIRMED for state in non_cancelled):
        return BOOKING_HEADER_CONFIRMED
    return BOOKING_HEADER_IN_PROGRESS


def resolve_r3_cancel_action():
    from iroad_tenants.operation_runtime.action_master_catalog import (
        resolve_cancel_booking_action,
    )

    return resolve_cancel_booking_action()


def append_booking_r3_cancel_action_log(
    *,
    booking,
    created_by_label: str = '',
    tenant_user=None,
    notes: str = '',
):
    """Append R3 cancel entry to the Action Log (PCS §3.8.4)."""
    from iroad_tenants.views import (
        OPERATION_ACTION_LOG_AUTO_FORM_CODE,
        OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
        OPERATION_ACTION_LOG_REF_PREFIX,
        _next_auto_number_for_form,
    )
    from tenant_workspace.models import TenantOperationActionLog

    operation_action = resolve_r3_cancel_action()
    if operation_action is None:
        return None

    log_no = ''
    log_sequence = 0
    for _ in range(10):
        log_no, log_sequence = _next_auto_number_for_form(
            form_code=OPERATION_ACTION_LOG_AUTO_FORM_CODE,
            form_label=OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
            prefix=OPERATION_ACTION_LOG_REF_PREFIX,
        )
        if not TenantOperationActionLog.objects.filter(log_no=log_no).exists():
            break
    if TenantOperationActionLog.objects.filter(log_no=log_no).exists():
        return None

    note_text = (notes or '').strip() or 'Booking cancelled by admin (R3).'
    return TenantOperationActionLog.objects.create(
        log_no=log_no,
        log_sequence=log_sequence,
        log_date=timezone.now(),
        operation_action=operation_action,
        source='Admin Reversal',
        source_channel='admin_manual',
        notes=note_text,
        booking=booking,
        created_by=tenant_user,
        created_by_label=(created_by_label or '')[:200],
    )
