"""
mobile_api/dashboard/projections/job_location_dashboard.py

Route + pickup/drop blocks for dashboard ``active_job`` / ``active_shipment``.
"""
from __future__ import annotations

from typing import Any

from mobile_api.dashboard.selectors import booking_selection_policy as policy
from mobile_api.helpers.booking_endpoint_addresses import (
    resolve_booking_endpoint_addresses,
)
from mobile_api.helpers.job_booking_meta import (
    resolve_client_name,
    resolve_execution_date,
)
from mobile_api.helpers.order_type import resolve_order_type_text
from mobile_api.helpers.route_backload_proxy import backload_route_booking_proxy


def build_dashboard_active_job(
    *,
    shipment: Any | None = None,
    booking: Any | None = None,
    movement: Any | None = None,
    driver: Any | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """
    Mobile ``active_job`` slice (same location fields as Job Detail ``data.job``).

    Shipment job takes precedence when both shipment and movement are set.
    """
    from mobile_api.job_detail.projections.job_location_projection import (
        build_movement_location_block,
        build_shipment_location_block,
        serialize_route,
    )

    from mobile_api.helpers.backload_booking_redirect import (
        should_pivot_shipment_to_backload_booking,
    )

    if (
        shipment is not None
        and booking is not None
        and driver is not None
        and should_pivot_shipment_to_backload_booking(
            driver=driver,
            booking=booking,
            shipment=shipment,
        )
    ):
        shipment = None

    if shipment is not None:
        shipment_id = getattr(shipment, 'shipment_id', None) or getattr(
            shipment, 'pk', None
        )
        block = {
            'job_type': 'shipment',
            'job_id': str(shipment_id) if shipment_id is not None else '',
            'job_no': str(getattr(shipment, 'shipment_no', '') or ''),
            'entity_type': 'shipment',
            'order_type': resolve_order_type_text(
                shipment=shipment,
                booking=booking,
            ),
            'client_name': resolve_client_name(
                shipment=shipment,
                booking=booking,
                request=request,
            ),
            'execution_date': resolve_execution_date(
                shipment=shipment,
                booking=booking,
            ),
        }
        block.update(
            build_shipment_location_block(
                shipment,
                booking=booking,
                request=request,
            ),
        )
        return block

    if movement is not None:
        movement_id = getattr(movement, 'movement_id', None) or getattr(
            movement, 'pk', None
        )
        movement_shipment = getattr(movement, 'shipment', None)
        movement_booking = booking or getattr(movement, 'booking', None)
        block = {
            'job_type': 'movement',
            'job_id': str(movement_id) if movement_id is not None else '',
            'job_no': str(getattr(movement, 'movement_no', '') or ''),
            'entity_type': 'movement',
            'order_type': resolve_order_type_text(
                shipment=movement_shipment,
                booking=movement_booking,
            ),
            'client_name': resolve_client_name(
                shipment=movement_shipment,
                booking=movement_booking,
                request=request,
            ),
            'execution_date': resolve_execution_date(
                shipment=movement_shipment,
                booking=movement_booking,
            ),
        }
        block.update(build_movement_location_block(movement, request=request))
        return block

    if booking is not None:
        booking_id = getattr(booking, 'booking_id', None) or getattr(booking, 'pk', None)
        shipments = list(
            booking.shipments.all() if hasattr(booking, 'shipments') else []
        )
        stage = policy.derive_booking_execution_stage(
            booking, shipments, driver=driver
        )
        show_backload_route = policy.should_display_backload_route(
            booking,
            shipments,
            booking_stage=stage,
        )
        route_booking = booking
        if show_backload_route:
            route_booking = backload_route_booking_proxy(booking)
        is_backload_bootstrap = policy.is_backload_leg_pending(booking, shipments)
        if is_backload_bootstrap and driver is not None:
            is_backload_bootstrap = policy.driver_owns_backload_leg(driver, booking)
        pickup_address, drop_address = resolve_booking_endpoint_addresses(
            booking,
            leg_is_backload=(
                is_backload_bootstrap
                or show_backload_route
                or stage == policy.BOOKING_EXECUTION_STAGE_OUTBOUND_COMPLETED
            ),
            request=request,
        )
        booking_item_type = 'Backload' if is_backload_bootstrap else 'Outbound'
        block = {
            'job_type': 'booking',
            'job_id': str(booking_id) if booking_id is not None else '',
            'job_no': str(getattr(booking, 'booking_no', '') or ''),
            'entity_type': 'booking',
            'booking_item_type': booking_item_type,
            'order_type': resolve_order_type_text(
                shipment=None,
                booking=booking,
            ),
            'client_name': resolve_client_name(
                shipment=None,
                booking=booking,
                request=request,
            ),
            'execution_date': resolve_execution_date(
                shipment=None,
                booking=booking,
            ),
            'route': serialize_route(booking=route_booking, request=request),
            'pickup_address': pickup_address,
            'drop_address': drop_address,
            'booking_execution_stage': stage or '',
        }
        if is_backload_bootstrap:
            block['backload_bootstrap_pending'] = True
        return block

    return {}
