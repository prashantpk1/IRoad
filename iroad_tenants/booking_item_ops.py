"""Booking item delete/cancel for round trips (PCS §3.7)."""
from __future__ import annotations

from django.utils import timezone

from iroad_tenants.booking_status import sync_booking_status_after_item_change

DB_TRIP_ROUND = 'Round'
DB_TRIP_ONE_WAY = 'One-Way'
LINE_OUTBOUND = 'Outbound'
LINE_BACKLOAD = 'Backload'

SHIPMENT_CANCELLED = 'Cancelled'
SHIPMENT_CLOSED = 'Closed'


def _line_shipments(booking, line_type: str):
    from tenant_workspace.models import TenantShipment

    return TenantShipment.objects.filter(
        booking_id=booking.booking_id,
        booking_item_type=(line_type or '').strip(),
    )


def booking_line_action_flags(booking, line_type: str) -> dict:
    """Per-line delete/cancel eligibility (edit round trip only)."""
    flags = {'can_delete': False, 'can_cancel': False}
    if booking is None or (booking.trip_type or '').strip() != DB_TRIP_ROUND:
        return flags
    normalized = (line_type or '').strip()
    if normalized not in {LINE_OUTBOUND, LINE_BACKLOAD}:
        return flags

    shipments = list(_line_shipments(booking, normalized))
    if not shipments:
        flags['can_delete'] = True
        return flags

    active_exists = any(
        (s.shipment_status or '').strip() not in {SHIPMENT_CANCELLED, SHIPMENT_CLOSED}
        for s in shipments
    )
    cancelled_exists = any(
        (s.shipment_status or '').strip() == SHIPMENT_CANCELLED for s in shipments
    )
    if cancelled_exists and not active_exists:
        flags['can_cancel'] = True
    return flags


def booking_line_actions_map(booking) -> dict:
    if booking is None or (booking.trip_type or '').strip() != DB_TRIP_ROUND:
        return {}
    return {
        LINE_OUTBOUND: booking_line_action_flags(booking, LINE_OUTBOUND),
        LINE_BACKLOAD: booking_line_action_flags(booking, LINE_BACKLOAD),
    }


def _route_labels(booking):
    route = getattr(booking, 'route', None)
    if route is None or not getattr(route, 'origin_point', None):
        return '', ''
    forward = (
        f'{route.origin_point.display_label} To {route.destination_point.display_label}'
    )
    reverse = (
        f'{route.destination_point.display_label} To {route.origin_point.display_label}'
    )
    return forward, reverse


def _apply_route_after_item_removal(booking, *, removed_line: str) -> None:
    forward, reverse = _route_labels(booking)
    if removed_line == LINE_OUTBOUND:
        booking.route_direction = 'reverse'
        booking.route_display = reverse or booking.route_display
    else:
        booking.route_direction = 'forward'
        booking.route_display = forward or booking.route_display


def _clear_backload_fields(booking) -> None:
    booking.booking_line_backload_truck = None
    booking.booking_line_backload_driver = None
    booking.booking_line_backload_cod_amount = 0
    booking.booking_line_backload_pod_doc_count = 0


_BOOKING_ITEM_UPDATE_FIELDS = [
    'trip_type',
    'route_direction',
    'route_display',
    'assigned_truck',
    'assigned_driver',
    'booking_line_cod_amount',
    'booking_line_pod_doc_count',
    'booking_line_backload_truck',
    'booking_line_backload_driver',
    'booking_line_backload_cod_amount',
    'booking_line_backload_pod_doc_count',
    'loading_booking_item',
    'delivery_booking_item',
    'cargo_booking_item',
    'booking_status',
    'updated_at',
]


def _save_booking_after_item_change(booking) -> None:
    sync_booking_status_after_item_change(booking)
    booking.save(update_fields=_BOOKING_ITEM_UPDATE_FIELDS)


def _promote_backload_to_outbound(booking) -> None:
    booking.assigned_truck = booking.booking_line_backload_truck
    booking.assigned_driver = booking.booking_line_backload_driver
    booking.booking_line_cod_amount = booking.booking_line_backload_cod_amount or 0
    booking.booking_line_pod_doc_count = booking.booking_line_backload_pod_doc_count or 0
    _clear_backload_fields(booking)
    booking.loading_booking_item = LINE_OUTBOUND
    booking.delivery_booking_item = LINE_OUTBOUND
    booking.cargo_booking_item = LINE_OUTBOUND


def apply_booking_item_delete(booking, line_type: str) -> list[str]:
    """Delete one round-trip item (no shipment). Returns validation errors."""
    flags = booking_line_action_flags(booking, line_type)
    if not flags['can_delete']:
        return ['This booking item cannot be deleted.']

    normalized = (line_type or '').strip()
    if normalized == LINE_OUTBOUND:
        _promote_backload_to_outbound(booking)
    elif normalized == LINE_BACKLOAD:
        _clear_backload_fields(booking)
        booking.loading_booking_item = LINE_OUTBOUND
        booking.delivery_booking_item = LINE_OUTBOUND
        booking.cargo_booking_item = LINE_OUTBOUND
    else:
        return ['Unknown booking item type.']

    booking.trip_type = DB_TRIP_ONE_WAY
    _apply_route_after_item_removal(booking, removed_line=normalized)
    _save_booking_after_item_change(booking)
    return []


def apply_booking_item_cancel(booking, line_type: str) -> list[str]:
    """Cancel one round-trip item (shipment already cancelled). Returns validation errors."""
    flags = booking_line_action_flags(booking, line_type)
    if not flags['can_cancel']:
        return ['This booking item cannot be cancelled.']

    normalized = (line_type or '').strip()
    if normalized == LINE_OUTBOUND:
        _promote_backload_to_outbound(booking)
    elif normalized == LINE_BACKLOAD:
        _clear_backload_fields(booking)
        booking.loading_booking_item = LINE_OUTBOUND
        booking.delivery_booking_item = LINE_OUTBOUND
        booking.cargo_booking_item = LINE_OUTBOUND
    else:
        return ['Unknown booking item type.']

    booking.trip_type = DB_TRIP_ONE_WAY
    _apply_route_after_item_removal(booking, removed_line=normalized)
    _save_booking_after_item_change(booking)
    return []


def resolve_r2_cancel_item_action():
    from iroad_tenants.operation_runtime.action_master_catalog import PRODUCTION_ACTION_MASTER
    from tenant_workspace.models import TenantOperationAction

    row = TenantOperationAction.objects.filter(action_code__iexact='R2').first()
    if row is not None:
        return row
    spec = next((s for s in PRODUCTION_ACTION_MASTER if s.action_code.upper() == 'R2'), None)
    if spec is None:
        return None
    model_fields = {field.name for field in TenantOperationAction._meta.fields}
    return TenantOperationAction.objects.create(
        action_code=spec.action_code,
        **spec.defaults(model_fields),
    )


def append_booking_r2_item_action_log(
    *,
    booking,
    line_type: str,
    created_by_label: str = '',
    tenant_user=None,
    notes: str = '',
):
    from iroad_tenants.views import (
        OPERATION_ACTION_LOG_AUTO_FORM_CODE,
        OPERATION_ACTION_LOG_AUTO_FORM_LABEL,
        OPERATION_ACTION_LOG_REF_PREFIX,
        _next_auto_number_for_form,
    )
    from tenant_workspace.models import TenantOperationActionLog

    operation_action = resolve_r2_cancel_item_action()
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

    note_text = (notes or '').strip() or (
        f'Booking item {line_type} cancelled by admin (R2). '
        f'Trip type updated to One-Way.'
    )
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
