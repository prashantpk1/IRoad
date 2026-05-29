"""
Operational action policy engine (Gap 2 — dynamic action calculator).

Used by tenant admin Action Log create/edit and future mobile APIs.
Admin manual entry remains supported; rules filter dropdown and block invalid POST.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Q

from iroad_tenants.operation_runtime.shipment_execution_stage import (
    STAGE_COD,
    STAGE_COMPLETION,
    STAGE_POD,
    STAGE_PRE_TRANSIT,
    derive_shipment_execution_stage,
    execution_stage_operational_label,
    is_pickup_or_loading_action,
    shipment_allows_pickup_loading_action,
)
from tenant_workspace.models import (
    TenantBooking,
    TenantOperationAction,
    TenantOperationActionLog,
    TenantShipment,
    TenantTruckMovementLog,
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


def _shipment_has_active_movement(shipment):
    if shipment is None:
        return False
    return (
        TenantTruckMovementLog.objects.filter(shipment_id=shipment.pk)
        .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
        .exists()
    )


def _action_requires_movement(action) -> bool:
    """
    Returns True for actions that require an existing
    active movement record to execute.
    These are actions that advance or complete movement
    but do NOT create it.
    A4 creates movement — not included here.
    """
    action_code = (
        getattr(action, 'action_code', '') or ''
    ).upper().strip()

    movement_dependent_codes = {
        'A5', 'A8',
    }
    if action_code in movement_dependent_codes:
        return True

    movement_impact = (
        getattr(action, 'movement_status_impact', '')
        or ''
    ).strip()
    if movement_impact and action_code != 'A4':
        return True

    return False


def _executed_action_ids(*, booking=None, shipment=None, movement=None, exclude_log_id=None):
    qs = TenantOperationActionLog.objects.exclude(operation_action__isnull=True)
    if exclude_log_id:
        qs = qs.exclude(log_id=exclude_log_id)
    if shipment is not None:
        qs = qs.filter(shipment_id=shipment.pk)
    elif movement is not None:
        from iroad_tenants.operation_runtime.movement_execution_engine import (
            movement_executed_action_ids,
        )

        return movement_executed_action_ids(movement, exclude_log_id=exclude_log_id)
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
    executed_action_ids=None,
):
    if action is None or action.status != TenantOperationAction.Status.ACTIVE:
        return False

    if include_action_id and str(action.action_id) == str(include_action_id):
        return True

    if _is_reversal_action(action):
        if shipment is None:
            return booking is not None
        return shipment.shipment_status not in _TERMINAL_SHIPMENT_STATUSES

    executed_ids = (
        executed_action_ids
        if executed_action_ids is not None
        else _executed_action_ids(
            booking=booking,
            shipment=shipment,
            movement=movement,
            exclude_log_id=exclude_log_id,
        )
    )
    if action.action_id in executed_ids:
        return False

    impact = resolve_shipment_status_impact(action.shipment_status_impact)

    # --- Shipment linked: forward / side-effect actions ---
    if shipment is not None:
        current = shipment.shipment_status or ''
        if current in _TERMINAL_SHIPMENT_STATUSES:
            return _is_reversal_action(action)

        has_active_movement = _shipment_has_active_movement(
            shipment
        )
        action_code = str(getattr(action, 'action_code', '') or '').strip().upper()
        is_confirm_loaded = (
            action_code == 'A4'
            or action_matches(action, 'confirm loaded',
                              'confirm_loaded')
        )

        if action.auto_shipment_post and not is_confirm_loaded:
            return False

        # A4 is the action that CREATES movement.
        # Allow A4 when movement does not exist yet
        # and shipment is in pre-movement status.
        if is_confirm_loaded:
            if not has_active_movement:
                return current in {
                    TenantShipment.ShipmentStatus.CREATED,
                    TenantShipment.ShipmentStatus.LOADED,
                }
            else:
                # Movement already exists — A4 already fired
                return False

        # All other movement-dependent actions (A5, A8 etc)
        # require movement to exist first.
        # This is a hard block — cannot be bypassed.
        requires_existing_movement = _action_requires_movement(
            action
        )
        if requires_existing_movement and not has_active_movement:
            return False

        if action_matches(action, 'collect payment', 'a9', 'action 9'):
            if (shipment.order_type or '').upper() != 'COD':
                return False
            return current in {
                TenantShipment.ShipmentStatus.IN_TRANSIT,
                TenantShipment.ShipmentStatus.AT_DELIVERY,
                TenantShipment.ShipmentStatus.POD_SUBMITTED,
                TenantShipment.ShipmentStatus.DELIVERED,
            }

        if action_matches(action, 'start job', 'action 1') or action_code == 'A1':
            return False

        if impact:
            if (
                impact == TenantShipment.ShipmentStatus.IN_TRANSIT
                and current
                in {
                    TenantShipment.ShipmentStatus.CREATED,
                    TenantShipment.ShipmentStatus.LOADED,
                }
                and derive_shipment_execution_stage(
                    shipment,
                    exclude_log_id=exclude_log_id,
                )
                != STAGE_PRE_TRANSIT
            ):
                return False
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

        if is_pickup_or_loading_action(action):
            return shipment_allows_pickup_loading_action(
                action,
                shipment,
                exclude_log_id=exclude_log_id,
            )

        if action.booking_status_impact and not impact:
            return False

        movement_token = (
            (action.movement_status_impact or '')
            .strip()
            .lower()
            .replace('-', '_')
            .replace(' ', '_')
        )
        if movement_token:
            if movement_token == 'completed':
                return derive_shipment_execution_stage(
                    shipment,
                    exclude_log_id=exclude_log_id,
                ) in {STAGE_POD, STAGE_COD, STAGE_COMPLETION}
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

    # --- Movement-only (empty move / no shipment on context) ---
    if movement is not None:
        from iroad_tenants.operation_runtime.movement_execution_engine import (
            is_movement_only_context,
            movement_action_allowed,
        )

        if is_movement_only_context(shipment=shipment, movement=movement):
            return movement_action_allowed(
                action,
                movement=movement,
                exclude_log_id=exclude_log_id,
                include_action_id=include_action_id,
            )
        if shipment is None and booking is None:
            return movement_action_allowed(
                action,
                movement=movement,
                exclude_log_id=exclude_log_id,
                include_action_id=include_action_id,
            )
        return bool(
            (action.movement_status_impact or '').strip()
            or action.auto_movement_post
        )

    return False


def get_allowed_actions(
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type='',
    exclude_log_id=None,
    include_action_id=None,
    for_mobile: bool = True,
):
    """
    Return TenantOperationAction queryset allowed for the current operational context.

    Uses DB-side candidate narrowing (scope, stage, executed dedupe) before the
    policy engine pass — avoids scanning the full ACTIVE Action Config catalog.
    """
    from iroad_tenants.operation_runtime.allowed_actions_query import (
        prefilter_allowed_action_candidates,
    )

    executed_ids = _executed_action_ids(
        booking=booking,
        shipment=shipment,
        movement=movement,
        exclude_log_id=exclude_log_id,
    )

    candidates = prefilter_allowed_action_candidates(
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
        executed_action_ids=executed_ids,
        exclude_log_id=exclude_log_id,
        for_mobile=for_mobile,
    )

    allowed_ids: list = []
    for action in candidates.iterator(chunk_size=64):
        if _action_is_allowed(
            action,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            exclude_log_id=exclude_log_id,
            include_action_id=include_action_id,
            executed_action_ids=executed_ids,
        ):
            allowed_ids.append(action.action_id)

    if include_action_id and str(include_action_id) not in {
        str(action_id) for action_id in allowed_ids
    }:
        preserved = TenantOperationAction.objects.filter(
            pk=include_action_id,
            status=TenantOperationAction.Status.ACTIVE,
        ).first()
        if preserved is not None and _action_is_allowed(
            preserved,
            booking=booking,
            shipment=shipment,
            movement=movement,
            booking_item_type=booking_item_type,
            exclude_log_id=exclude_log_id,
            include_action_id=include_action_id,
            executed_action_ids=executed_ids,
        ):
            allowed_ids.append(preserved.action_id)

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

    action_code = str(getattr(operation_action, 'action_code', '') or '').strip().upper()
    if action_code == 'A4' and shipment is not None:
        has_movement = (
            TenantTruckMovementLog.objects.filter(shipment_id=shipment.pk)
            .exclude(status=TenantTruckMovementLog.Status.CANCELLED)
            .exists()
        )
        if not has_movement:
            raise ValidationError(
                'Data integrity error: Shipment exists without Movement. '
                'Contact admin to repair this record. '
                'error_code: shipment_without_movement'
            )

    context_bits = []
    if shipment is not None:
        context_bits.append(f'shipment status is {shipment.shipment_status}')
    elif movement is not None:
        from iroad_tenants.operation_runtime.movement_execution_engine import (
            movement_allowed_actions_context_label,
        )

        context_bits.append(movement_allowed_actions_context_label(movement))
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


def get_action_master_options():
    """All active Action Master rows for FK dropdowns (english_label display)."""
    return TenantOperationAction.objects.filter(
        status=TenantOperationAction.Status.ACTIVE,
    ).order_by('sequence_number', 'action_code')


def _has_action_dropdown_context(*, booking=None, shipment=None, movement=None):
    return booking is not None or shipment is not None or movement is not None


def get_action_dropdown_options(
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type='',
    exclude_log_id=None,
    include_action_id=None,
    for_mobile: bool = True,
):
    """
    Return queryset for the Action Log FK dropdown.
    Without booking/shipment/movement: all active Action Master rows.
    With context: workflow-filtered allowed actions only.
    """
    if not _has_action_dropdown_context(
        booking=booking,
        shipment=shipment,
        movement=movement,
    ):
        return get_action_master_options()

    return get_allowed_actions(
        booking=booking,
        shipment=shipment,
        movement=movement,
        booking_item_type=booking_item_type,
        exclude_log_id=exclude_log_id,
        include_action_id=include_action_id,
        for_mobile=for_mobile,
    )


def action_options_payload(actions):
    return [
        {
            'action_id': str(action.action_id),
            'action_code': action.action_code,
            'label': action.english_label or action.action_code,
            'english_label': action.english_label or action.action_code,
        }
        for action in actions
    ]


def action_dropdown_context_label(
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type='',
):
    if not _has_action_dropdown_context(
        booking=booking,
        shipment=shipment,
        movement=movement,
    ):
        return 'Active actions from Action Master (english label). Link booking or shipment to filter by workflow.'

    return allowed_actions_context_label(
        booking=booking,
        shipment=shipment,
        booking_item_type=booking_item_type,
    )


def allowed_actions_context_label(*, booking=None, shipment=None, booking_item_type=''):
    if shipment is not None:
        stage = derive_shipment_execution_stage(shipment)
        label = execution_stage_operational_label(stage) or shipment.shipment_status
        return f'Allowed actions for shipment execution stage: {label}'
    if booking is not None:
        line = (booking_item_type or '').strip()
        if line:
            return f'Allowed actions for booking {booking.booking_no} ({line}) — no shipment selected'
        return f'Allowed actions for booking {booking.booking_no} — no shipment selected'
    return 'Select a booking or shipment to see allowed actions.'
