"""
DB-side candidate narrowing for ``get_allowed_actions()`` (Job Detail / mobile).

Policy truth remains ``_action_is_allowed``; this module only shrinks the ACTIVE
catalog before the final per-row engine pass.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from tenant_workspace.models import (
    TenantBooking,
    TenantOperationAction,
    TenantShipment,
)

# Mirrors operation_execution forward-path map (kept local to avoid import cycles).
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
from iroad_tenants.operation_runtime.action_config_cache import (
    active_operation_actions_queryset,
)
from iroad_tenants.operation_runtime.movement_action_validator import (
    action_applies_to_movement_context,
    is_empty_movement,
    is_movement_only_context,
)
from iroad_tenants.operation_runtime.shipment_execution_stage import (
    STAGE_COD,
    STAGE_COMPLETION,
    STAGE_PICKUP,
    STAGE_LOADING,
    STAGE_PRE_TRANSIT,
    STAGE_CANCELLED,
    derive_shipment_execution_stage,
)
# Mobile driver Job Detail — exclude dispatch/on-call catalog rows at the DB.
_MOBILE_JOB_ACTION_SCOPES = ('job', 'without', '')

# Shipment_status_impact column tokens that map to forward targets from current status.
_SHIPMENT_IMPACT_DB_TOKENS = {
    TenantShipment.ShipmentStatus.IN_TRANSIT: (
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        'In Transit',
        'in_transit',
    ),
    TenantShipment.ShipmentStatus.AT_DELIVERY: (
        TenantShipment.ShipmentStatus.AT_DELIVERY,
        'At Delivery',
        'at_delivery',
    ),
    TenantShipment.ShipmentStatus.POD_SUBMITTED: (
        TenantShipment.ShipmentStatus.POD_SUBMITTED,
        'POD Submitted',
        'pod_submitted',
    ),
    TenantShipment.ShipmentStatus.DELIVERED: (
        TenantShipment.ShipmentStatus.DELIVERED,
        'Delivered',
        'delivered',
    ),
    TenantShipment.ShipmentStatus.CLOSED: (
        TenantShipment.ShipmentStatus.CLOSED,
        'Closed',
        'closed',
    ),
}

_COD_ACTION_CODE_HINTS = ('a9', 'action 9')
_COD_LABEL_HINT = 'collect payment'

_PICKUP_CODE_HINTS = ('a2', 'action 2')
_LOADING_CODE_HINTS = ('a3', 'action 3')

_REVERSAL_CODE_PREFIXES = ('r1', 'r2', 'r3', 'r4')


def _forward_impact_tokens_for_status(current_status: str) -> list[str]:
    tokens: list[str] = []
    for impact_status, from_statuses in _FORWARD_FROM_STATUSES.items():
        if current_status not in from_statuses:
            continue
        tokens.extend(_SHIPMENT_IMPACT_DB_TOKENS.get(impact_status, (impact_status,)))
    # De-dupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        norm = (token or '').strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _apply_mobile_scope_filter(qs: QuerySet) -> QuerySet:
    return qs.filter(action_scope__in=_MOBILE_JOB_ACTION_SCOPES)


def _exclude_executed(qs: QuerySet, executed_ids: set) -> QuerySet:
    if executed_ids:
        qs = qs.exclude(action_id__in=executed_ids)
    return qs


def _prefilter_shipment_candidates(
    qs: QuerySet,
    *,
    shipment,
    exclude_log_id=None,
) -> QuerySet:
    current = (shipment.shipment_status or '').strip()
    stage = derive_shipment_execution_stage(
        shipment,
        exclude_log_id=exclude_log_id,
    )

    qs = qs.filter(auto_shipment_post=False)

    if current in _TERMINAL_SHIPMENT_STATUSES or stage in (STAGE_COMPLETION, STAGE_CANCELLED):
        reversal_q = Q()
        for prefix in _REVERSAL_CODE_PREFIXES:
            reversal_q |= Q(action_code__istartswith=prefix)
        reversal_q |= Q(english_label__icontains='reversal')
        reversal_q |= Q(english_label__icontains='reject')
        reversal_q |= Q(english_label__icontains='undo')
        reversal_q |= Q(english_label__icontains='cancel shipment')
        return qs.filter(
            Q(shipment_status_impact='') | reversal_q,
        ).exclude(
            Q(booking_status_impact__gt='') & Q(shipment_status_impact=''),
        )

    clauses = Q()

    if current in {
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.LOADED,
    } and stage != STAGE_PRE_TRANSIT:
        forward_tokens = []
    else:
        forward_tokens = _forward_impact_tokens_for_status(current)
    if forward_tokens:
        clauses |= Q(shipment_status_impact__in=forward_tokens)

    if stage in (STAGE_PICKUP, STAGE_LOADING, STAGE_PRE_TRANSIT):
        pickup_q = Q()
        loading_q = Q()
        for hint in _PICKUP_CODE_HINTS:
            pickup_q |= Q(action_code__icontains=hint) | Q(english_label__icontains='pickup')
        for hint in _LOADING_CODE_HINTS:
            loading_q |= Q(action_code__icontains=hint) | Q(english_label__icontains='loading')
        clauses |= pickup_q | loading_q
        clauses |= Q(auto_movement_post=True) | Q(auto_pod_post=True)
        clauses |= Q(shipment_status_impact='')

    if stage == STAGE_COD or (
        (shipment.order_type or '').upper() == 'COD'
        and current
        in {
            TenantShipment.ShipmentStatus.IN_TRANSIT,
            TenantShipment.ShipmentStatus.AT_DELIVERY,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
            TenantShipment.ShipmentStatus.DELIVERED,
        }
    ):
        cod_q = Q()
        for hint in _COD_ACTION_CODE_HINTS:
            cod_q |= Q(action_code__icontains=hint)
        cod_q |= Q(english_label__icontains=_COD_LABEL_HINT)
        clauses |= cod_q

    if current in {
        TenantShipment.ShipmentStatus.LOADED,
        TenantShipment.ShipmentStatus.CREATED,
        TenantShipment.ShipmentStatus.IN_TRANSIT,
        TenantShipment.ShipmentStatus.AT_DELIVERY,
    }:
        clauses |= Q(auto_movement_post=True) | Q(auto_pod_post=True)

    if clauses:
        qs = qs.filter(clauses)
    else:
        qs = qs.filter(
            Q(shipment_status_impact='')
            | Q(auto_movement_post=True)
            | Q(auto_pod_post=True)
            | Q(movement_status_impact__gt=''),
        )

    qs = qs.exclude(
        Q(booking_status_impact__gt='')
        & Q(shipment_status_impact='')
        & Q(movement_status_impact='')
        & Q(auto_movement_post=False)
        & Q(auto_pod_post=False),
    )
    return qs


def _prefilter_booking_candidates(qs: QuerySet, *, booking) -> QuerySet:
    if booking.booking_status == TenantBooking.Status.CANCELLED:
        reversal_q = Q()
        for prefix in _REVERSAL_CODE_PREFIXES:
            reversal_q |= Q(action_code__istartswith=prefix)
        return qs.filter(reversal_q | Q(english_label__icontains='reversal'))

    qs = qs.filter(
        Q(booking_status_impact__gt='') | Q(auto_shipment_post=True),
    )
    if booking.booking_status != TenantBooking.Status.CONFIRMED:
        qs = qs.exclude(auto_shipment_post=True)
    return qs.exclude(shipment_status_impact__gt='')


def _prefilter_movement_only_candidates(qs: QuerySet, *, movement) -> QuerySet:
    empty_move = is_empty_movement(movement)
    qs = qs.exclude(shipment_status_impact__gt='')
    qs = qs.exclude(
        Q(auto_shipment_post=True) & Q(movement_status_impact=''),
    )
    if empty_move:
        qs = qs.exclude(
            Q(sequence_category__iexact='job') & Q(movement_status_impact=''),
        )
    return qs.filter(
        Q(movement_status_impact__gt='')
        | Q(sequence_category__iexact='empty_move')
        | Q(auto_movement_post=True)
        | Q(action_code__istartswith='m')
        | Q(english_label__icontains='movement'),
    )


def prefilter_allowed_action_candidates(
    *,
    booking=None,
    shipment=None,
    movement=None,
    booking_item_type: str = '',
    executed_action_ids: set | None = None,
    exclude_log_id=None,
    for_mobile: bool = True,
) -> QuerySet:
    """
    Narrow ACTIVE Action Config rows before ``_action_is_allowed`` evaluation.
    """
    qs = active_operation_actions_queryset()
    if for_mobile:
        qs = _apply_mobile_scope_filter(qs)

    executed = executed_action_ids or set()
    qs = _exclude_executed(qs, executed)

    if shipment is not None:
        return _prefilter_shipment_candidates(
            qs,
            shipment=shipment,
            exclude_log_id=exclude_log_id,
        )

    if booking is not None and movement is None:
        return _prefilter_booking_candidates(qs, booking=booking)

    if movement is not None and is_movement_only_context(
        shipment=shipment,
        movement=movement,
    ):
        return _prefilter_movement_only_candidates(qs, movement=movement)

    if movement is not None and shipment is None and booking is None:
        return _prefilter_movement_only_candidates(qs, movement=movement)

    if movement is not None:
        qs = qs.filter(
            Q(movement_status_impact__gt='') | Q(auto_movement_post=True),
        )
        return qs

    return qs.none()


def movement_context_db_prefilter(
    actions: QuerySet,
    *,
    movement,
) -> list:
    """
    Apply movement-context classifier on a queryset (DB pass + small residual list).

    Used when a movement queryset was already narrowed but still needs
    ``action_applies_to_movement_context`` semantics.
    """
    empty_move = is_empty_movement(movement)
    narrowed = _prefilter_movement_only_candidates(actions, movement=movement)
    return [
        action
        for action in narrowed
        if action_applies_to_movement_context(action, empty_move=empty_move)
    ]
