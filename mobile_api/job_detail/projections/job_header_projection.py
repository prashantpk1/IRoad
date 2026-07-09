"""
mobile_api/job_detail/projections/job_header_projection.py

``job`` section — identity, status labels, assignment, route summary (read-only).
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.cod_amount import build_cod_payment_display
from mobile_api.helpers.job_booking_meta import (
    resolve_client_name,
    resolve_execution_date,
    resolve_execution_time,
)
from mobile_api.helpers.order_type import resolve_order_type_text
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.helpers.booking_endpoint_addresses import (
    resolve_booking_endpoint_addresses,
)
from mobile_api.job_detail.helpers.booking_job_context import (
    leg_is_backload_for_addresses,
    resolve_booking_job_execution_context,
)
from mobile_api.job_detail.projections.job_location_projection import (
    build_movement_location_block,
    build_shipment_location_block,
    serialize_route,
)
from mobile_api.job_detail.services.job_detail_projection_cache import (
    get_projection_cache,
)
from iroad_tenants.operation_runtime.movement_action_validator import is_empty_movement
from iroad_tenants.operation_runtime.movement_stage_derivation import (
    derive_movement_operational_stage,
)
from iroad_tenants.operation_runtime.movement_state_machine import execution_stage_label
from mobile_api.job_detail.services.job_detail_status_reconciler import (
    entity_reconciliation_block,
)


def build_job_header(
    context: JobDetailContext,
    *,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Build the unified ``job`` header block.

    Includes route, pickup (loading), and drop (delivery) addresses for navigation.
    """
    base: dict[str, Any] = {
        'job_type': context.job_type,
        'job_id': context.job_id,
        'job_no': '',
        'entity_type': context.job_type,
        'order_type': '',
        'client_name': '',
        'execution_date': '',
        'execution_time': '',
        'route': {},
        'pickup_address': {},
        'drop_address': {},
        'delivery_address': {},
    }

    if context.job_type == 'shipment' and context.shipment is not None:
        base['job_no'] = str(getattr(context.shipment, 'shipment_no', '') or '')
        base['order_type'] = resolve_order_type_text(
            shipment=context.shipment,
            booking=context.booking,
        )
        base['client_name'] = resolve_client_name(
            shipment=context.shipment,
            booking=context.booking,
            request=request,
        )
        base['execution_date'] = resolve_execution_date(
            shipment=context.shipment,
            booking=context.booking,
        )
        base.update(
            build_shipment_location_block(
                context.shipment,
                booking=context.booking,
                request=request,
            ),
        )
        base.update(
            build_cod_payment_display(
                shipment=context.shipment,
                booking=context.booking,
            ),
        )
        return base

    if context.job_type == 'movement' and context.movement is not None:
        base['job_no'] = str(getattr(context.movement, 'movement_no', '') or '')
        movement_shipment = getattr(context.movement, 'shipment', None)
        movement_booking = context.booking or getattr(
            context.movement,
            'booking',
            None,
        )
        base['order_type'] = resolve_order_type_text(
            shipment=movement_shipment,
            booking=movement_booking,
        )
        base['client_name'] = resolve_client_name(
            shipment=movement_shipment,
            booking=movement_booking,
            request=request,
        )
        base['execution_date'] = resolve_execution_date(
            shipment=movement_shipment,
            booking=movement_booking,
            movement=context.movement,
        )
        base['execution_time'] = resolve_execution_time(movement=context.movement)
        movement_logs = None
        if is_empty_movement(context.movement):
            cache = get_projection_cache(context)
            if cache is not None:
                movement_logs = list(cache.movement_logs or [])
        base.update(
            build_movement_location_block(
                context.movement,
                request=request,
                movement_logs=movement_logs,
            ),
        )
        recon = entity_reconciliation_block(context)
        auth_status = (recon.get('authoritative_status') or '').strip()
        column_status = (recon.get('column_status') or '').strip()
        operational = (recon.get('operational_stage') or '').strip()
        movement_status = auth_status or str(getattr(context.movement, 'status', '') or '')
        base['movement_status'] = movement_status
        base['column_movement_status'] = column_status or movement_status
        base['status_label'] = (
            operational
            or derive_movement_operational_stage(
                context.movement,
                status_for_stage=movement_status or None,
            )
            or execution_stage_label(movement_status)
            or movement_status
        )
        return base

    if context.job_type == 'booking' and context.booking is not None:
        booking = context.booking
        exec_ctx = resolve_booking_job_execution_context(context)
        route_booking = exec_ctx.get('route_booking') or booking
        leg_is_backload = leg_is_backload_for_addresses(exec_ctx)
        pickup_address, drop_address = resolve_booking_endpoint_addresses(
            booking,
            leg_is_backload=leg_is_backload,
            request=request,
        )

        base['job_no'] = str(getattr(booking, 'booking_no', '') or '')
        base['order_type'] = resolve_order_type_text(
            shipment=None,
            booking=booking,
        )
        base['client_name'] = resolve_client_name(
            shipment=None,
            booking=booking,
            request=request,
        )
        base['execution_date'] = resolve_execution_date(
            shipment=None,
            booking=booking,
        )
        base['route'] = serialize_route(booking=route_booking, request=request)
        base['pickup_address'] = pickup_address
        base['drop_address'] = drop_address
        if exec_ctx.get('booking_execution_stage'):
            base['booking_execution_stage'] = exec_ctx['booking_execution_stage']
        if exec_ctx.get('booking_item_type'):
            base['booking_item_type'] = exec_ctx['booking_item_type']
        if exec_ctx.get('backload_bootstrap'):
            base['backload_bootstrap_pending'] = True
            base['status_label'] = 'Return Trip'
            base['leg_label'] = 'Backload'
        elif exec_ctx.get('booking_execution_stage'):
            stage = str(exec_ctx.get('booking_execution_stage') or '').strip()
            if stage == 'OUTBOUND_COMPLETED':
                base['status_label'] = 'Return Trip'
        if (context.resolver_meta or {}).get('backload_booking_redirect'):
            base['backload_booking_redirect'] = True
            meta = context.resolver_meta or {}
            redirected_from = str(meta.get('redirected_from_shipment_id') or '').strip()
            if redirected_from:
                base['redirected_from_shipment_id'] = redirected_from
        if (context.resolver_meta or {}).get('closed_shipment_active_leg_redirect'):
            base['closed_shipment_active_leg_redirect'] = True
        return base

    return base
