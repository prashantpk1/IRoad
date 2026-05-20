"""
Operational action policy engine (Gap 2 — dynamic action calculator).

Used by tenant admin Action Log create/edit and future mobile APIs.
Admin manual entry remains supported; rules filter dropdown and block invalid POST.
"""

from __future__ import annotations

from django.db.models import Q

from tenant_workspace.models import (
    TenantBooking,
    TenantOperationAction,
    TenantOperationActionLog,
    TenantShipment,
)


def action_matches(action, *needles):
    if action is None:
        return False
    blob = f'{(action.action_code or "")} {(action.english_label or "")}'.lower()
    return any(needle.lower() in blob for needle in needles)


def resolve_shipment_status_impact(raw_value):
    """Map Action Master shipment_status_impact to TenantShipment.ShipmentStatus."""
    token = (raw_value or '').strip()
    if not token:
        return None
    if token in {choice[0] for choice in TenantShipment.ShipmentStatus.choices}:
        return token
    normalized = token.lower().replace('-', '_').replace(' ', '_')
    alias_map = {
        'loaded': TenantShipment.ShipmentStatus.LOADED,
        'created': TenantShipment.ShipmentStatus.CREATED,
        'in_transit': TenantShipment.ShipmentStatus.IN_TRANSIT,
        'at_delivery': TenantShipment.ShipmentStatus.AT_DELIVERY,
        'pod_submitted': TenantShipment.ShipmentStatus.POD_SUBMITTED,
        'delivered': TenantShipment.ShipmentStatus.DELIVERED,
        'closed': TenantShipment.ShipmentStatus.CLOSED,
        'cancelled': TenantShipment.ShipmentStatus.CANCELLED,
    }
    return alias_map.get(normalized)


# Forward lifecycle rank (higher = later phase).
_SHIPMENT_STATUS_RANK = {
    TenantShipment.ShipmentStatus.CREATED: 10,
    TenantShipment.ShipmentStatus.LOADED: 20,
    TenantShipment.ShipmentStatus.IN_TRANSIT: 30,
    TenantShipment.ShipmentStatus.AT_DELIVERY: 40,
    TenantShipment.ShipmentStatus.POD_SUBMITTED: 50,
    TenantShipment.ShipmentStatus.DELIVERED: 60,
    TenantShipment.ShipmentStatus.CLOSED: 70,
    TenantShipment.ShipmentStatus.CANCELLED: 99,
}

# Allowed current shipment_status before applying an impact (forward path).
_FORWARD_FROM_STATUSES = {
    TenantShipment.ShipmentStatus.IN_TRANSIT: {
        TenantShipment.ShipmentStatus.LOADED,
        TenantShipment.ShipmentStatus.CREATED,
    },
    TenantShipment.ShipmentStatus.AT_DELIVERY: {
        TenantShipment.ShipmentStatus.IN_TRANSIT,
    },
    TenantShipment.ShipmentStatus.POD_SUBMITTED: {
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        TenantShipment.ShipmentStatus.IN_TRANSIT,
    },
    TenantShipment.ShipmentStatus.DELIVERED: {
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
    },
    TenantShipment.ShipmentStatus.CLOSED: {
        TenantShipment.ShipmentStatus.DELIVERED,
    },
    TenantShipment.ShipmentStatus.LOADED: set(),
    TenantShipment.ShipmentStatus.CANCELLED: set(),
}

_TERMINAL_SHIPMENT_STATUSES = {
    TenantShipment.ShipmentStatus.CLOSED,
    TenantShipment.ShipmentStatus.CANCELLED,
}


def _is_reversal_action(action):
    return action_matches(
        action,
        'reversal',
        'reject pod',
        'reject',
        'r1',
        'r2',
        'r3',
        'r4',
        'cancel shipment',
        'undo',
    )


def _booking_has_active_shipment(booking, booking_item_type=''):
    if booking is None:
        return False
    qs = TenantShipment.objects.filter(booking_id=booking.booking_id).exclude(
        shipment_status__in=(
            TenantShipment.ShipmentStatus.CANCELLED,
            TenantShipment.ShipmentStatus.CLOSED,
        ),
    )
    line = (booking_item_type or '').strip()
    if line:
        qs = qs.filter(booking_item_type=line)
    return qs.exists()


def _executed_action_ids(*, booking=None, shipment=None, exclude_log_id=None):
    qs = TenantOperationActionLog.objects.exclude(operation_action__isnull=True)
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    if shipment is not None:
        qs = qs.filter(shipment_id=shipment.pk)
    elif booking is not None:
        qs = qs.filter(booking_id=booking.booking_id, shipment__isnull=True)
    else:
        return set()
    return set(qs.values_list('operation_action_id', flat=True))


def _booking_start_job_done(booking, *, exclude_log_id=None):
    if booking is None:
        return False
    if booking.execution_date is not None:
        return True
    qs = TenantOperationActionLog.objects.filter(booking_id=booking.booking_id).exclude(
        operation_action__isnull=True,
    )
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    for log in qs.select_related('operation_action')[:200]:
        if action_matches(log.operation_action, 'start job', 'a1', 'action 1'):
            return True
    return False


def _action_is_allowed(
    action,
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type='',
    exclude_log_id=None,
    include_action_id=None,
):
    if action is None or action.status != TenantOperationAction.Status.ACTIVE:
        return False

    if include_action_id and str(action.action_id) == str(include_action_id):
        return True

    if _is_reversal_action(action):
        if shipment is None:
            return booking is not None
        return shipment.shipment_status not in _TERMINAL_SHIPMENT_STATUSES

    executed_ids = _executed_action_ids(
        booking=booking,
        shipment=shipment,
        exclude_log_id=exclude_log_id,
    )
    if action.action_id in executed_ids:
        return False

    impact = resolve_shipment_status_impact(action.shipment_status_impact)

    # --- Shipment linked: forward / side-effect actions ---
    if shipment is not None:
        if action.auto_shipment_post:
            return False

        current = shipment.shipment_status or ''
        if current in _TERMINAL_SHIPMENT_STATUSES:
            return _is_reversal_action(action)

        if action_matches(action, 'collect payment', 'a9', 'action 9'):
            if (shipment.order_type or '').upper() != 'COD':
                return False
            return current in {
                TenantShipment.ShipmentStatus.IN_TRANSIT,
                TenantShipment.ShipmentStatus.AT_DELIVERY,
                TenantShipment.ShipmentStatus.POD_SUBMITTED,
                TenantShipment.ShipmentStatus.DELIVERED,
            }

        if action_matches(action, 'start job', 'a1', 'action 1'):
            return False

        if impact:
            allowed_from = _FORWARD_FROM_STATUSES.get(impact, set())
            if not allowed_from:
                return False
            if current not in allowed_from:
                return False
            target_rank = _SHIPMENT_STATUS_RANK.get(impact, 0)
            current_rank = _SHIPMENT_STATUS_RANK.get(current, 0)
            if target_rank <= current_rank:
                return False
            return True

        if action.auto_movement_post or action.auto_pod_post:
            return current in {
                TenantShipment.ShipmentStatus.LOADED,
                TenantShipment.ShipmentStatus.CREATED,
                TenantShipment.ShipmentStatus.IN_TRANSIT,
                TenantShipment.ShipmentStatus.AT_DELIVERY,
            }

        if action_matches(action, 'pickup', 'arrival', 'a2', 'action 2', 'start loading', 'a3', 'action 3'):
            return False

        if action.booking_status_impact and not impact:
            return False

        # Generic active action with no impact: allow only mid-lifecycle (manual audit).
        return current not in _TERMINAL_SHIPMENT_STATUSES

    # --- Booking only (no shipment on form) ---
    if booking is not None:
        if booking.booking_status == TenantBooking.Status.CANCELLED:
            return _is_reversal_action(action)

        if action.auto_shipment_post:
            if booking.booking_status != TenantBooking.Status.CONFIRMED:
                return False
            return not _booking_has_active_shipment(booking, booking_item_type)

        if action_matches(action, 'start job', 'a1', 'action 1'):
            if booking.booking_status not in {
                TenantBooking.Status.CONFIRMED,
                TenantBooking.Status.DRAFT,
            }:
                return False
            return not _booking_start_job_done(booking, exclude_log_id=exclude_log_id)

        if action_matches(
            action,
            'pickup',
            'arrival',
            'a2',
            'action 2',
            'start loading',
            'a3',
            'action 3',
        ):
            if booking.booking_status != TenantBooking.Status.CONFIRMED:
                return False
            return not _booking_has_active_shipment(booking, booking_item_type)

        if impact:
            return False

        if action.booking_status_impact:
            return booking.booking_status != TenantBooking.Status.CANCELLED

        return booking.booking_status == TenantBooking.Status.CONFIRMED

    # --- Movement without shipment (rare) ---
    if movement is not None:
        return bool(action.auto_movement_post or action.movement_status_impact)

    return False


def get_allowed_actions(
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type='',
    exclude_log_id=None,
    include_action_id=None,
):
    """
    Return TenantOperationAction queryset allowed for the current operational context.
    """
    actions = TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).order_by('sequence_number', 'action_code')

    allowed_ids = [
        action.action_id
        for action in actions
        if _action_is_allowed(
            action,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            exclude_log_id=exclude_log_id,
            include_action_id=include_action_id,
        )
    ]
    if not allowed_ids:
        return TenantOperationAction.objects.none()
    return TenantOperationAction.objects.filter(action_id__in=allowed_ids).order_by(
        'sequence_number',
        'action_code',
    )


def validate_operation_action_allowed(
    operation_action,
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type='',
    exclude_log_id=None,
    previous_action_id=None,
):
    """
    Return an error message if the action is not allowed; None if OK.
    On edit, changing to a new action is validated; keeping the same action is allowed.
    """
    if operation_action is None:
        return 'Invalid operation action selected.'

    include_id = None
    if previous_action_id and operation_action.pk == previous_action_id:
        include_id = previous_action_id

    allowed = get_allowed_actions(
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
        exclude_log_id=exclude_log_id,
        include_action_id=include_id,
    )
    if allowed.filter(pk=operation_action.pk).exists():
        return None

    context_bits = []
    if shipment is not None:
        context_bits.append(f'shipment status is {shipment.shipment_status}')
    elif booking is not None:
        context_bits.append(f'booking status is {booking.booking_status}')
    else:
        context_bits.append('no booking or shipment is linked')

    context_label = ', '.join(context_bits)
    return (
        f'Action "{operation_action.english_label or operation_action.action_code}" '
        f'is not allowed when {context_label}. '
        f'Choose an action that matches the current phase or link the correct booking/shipment.'
    )


def action_options_payload(actions):
    return [
        {
            'action_id': str(action.action_id),
            'action_code': action.action_code,
            'label': action.english_label or action.action_code,
        }
        for action in actions
    ]


def allowed_actions_context_label(*, booking=None, shipment=None, booking_item_type=''):
    if shipment is not None:
        return f'Allowed actions for shipment status: {shipment.shipment_status}'
    if booking is not None:
        line = (booking_item_type or '').strip()
        if line:
            return f'Allowed actions for booking {booking.booking_no} ({line}) — no shipment selected'
        return f'Allowed actions for booking {booking.booking_no} — no shipment selected'
    return 'Select a booking or shipment to see allowed actions.'
