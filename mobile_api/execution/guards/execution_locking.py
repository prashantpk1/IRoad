"""
mobile_api/execution/guards/execution_locking.py

Pessimistic row locks for execute transactions (shipment / movement / booking).
"""
from __future__ import annotations

import logging
from typing import Any

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.settings import mobile_execution_entity_locking_enabled

logger = logging.getLogger('mobile_api.execution')


def lock_execution_entities(
    context: ExecuteActionContext,
    *,
    operation_action: Any | None = None,
) -> None:
    """
    ``select_for_update`` on entities that can race during workflow progression.

    Must run inside the orchestrator ``transaction.atomic`` block.
    """
    if not mobile_execution_entity_locking_enabled():
        return

    from tenant_workspace.models import TenantBooking, TenantShipment, TenantTruckMovementLog

    if context.shipment is not None:
        ship_pk = getattr(context.shipment, 'pk', None) or getattr(
            context.shipment,
            'shipment_id',
            None,
        )
        if ship_pk:
            locked = (
                TenantShipment.objects.select_for_update()
                .filter(pk=ship_pk)
                .first()
            )
            if locked is not None:
                context.shipment = locked
                if context.booking is None and locked.booking_id:
                    context.booking = getattr(locked, 'booking', None)

    if context.movement is not None:
        mov_pk = getattr(context.movement, 'pk', None) or getattr(
            context.movement,
            'movement_id',
            None,
        )
        if mov_pk:
            locked_mov = (
                TenantTruckMovementLog.objects.select_for_update()
                .filter(pk=mov_pk)
                .first()
            )
            if locked_mov is not None:
                context.movement = locked_mov

    booking = context.booking
    if booking is None and context.shipment is not None:
        booking = getattr(context.shipment, 'booking', None)

    needs_booking_lock = _booking_progression_impacted(operation_action)
    if booking is not None and needs_booking_lock:
        bk_pk = getattr(booking, 'pk', None) or getattr(booking, 'booking_id', None)
        if bk_pk:
            locked_bk = (
                TenantBooking.objects.select_for_update()
                .filter(pk=bk_pk)
                .first()
            )
            if locked_bk is not None:
                context.booking = locked_bk
                if context.shipment is not None:
                    try:
                        context.shipment.booking = locked_bk
                    except Exception:
                        pass


def _booking_progression_impacted(operation_action: Any | None) -> bool:
    if operation_action is None:
        return False
    if (getattr(operation_action, 'booking_status_impact', None) or '').strip():
        return True
    if bool(getattr(operation_action, 'auto_shipment_post', False)):
        return True
    if bool(getattr(operation_action, 'auto_pod_post', False)):
        return True
    return False
