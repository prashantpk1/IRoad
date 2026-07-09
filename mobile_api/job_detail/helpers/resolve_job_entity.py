"""
Shared entity resolution for Job Detail and timeline APIs.
"""
from __future__ import annotations

from typing import Any

from mobile_api.helpers.backload_booking_redirect import (
    pivot_booking_to_active_shipment,
    pivot_closed_shipment_to_active_leg,
    pivot_context_to_backload_booking,
)
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.exceptions import job_detail_error_from_resolver
from mobile_api.job_detail.services.booking_job_resolver import BookingJobResolver
from mobile_api.job_detail.services.movement_job_resolver import MovementJobResolver
from mobile_api.job_detail.services.shipment_job_resolver import ShipmentJobResolver


def resolve_job_detail_entity(
    context: JobDetailContext,
    *,
    shipment_resolver: ShipmentJobResolver | None = None,
    movement_resolver: MovementJobResolver | None = None,
    booking_resolver: BookingJobResolver | None = None,
) -> None:
    """Resolve booking/shipment/movement on ``context``; pivot backload when needed."""
    shipment_resolver = shipment_resolver or ShipmentJobResolver()
    movement_resolver = movement_resolver or MovementJobResolver()
    booking_resolver = booking_resolver or BookingJobResolver()

    if context.job_type == 'shipment':
        result = shipment_resolver.resolve(
            context.driver,
            context.job_id,
            tenant_schema=context.tenant_schema,
        )
        if result.resolve_context is not None and not result.resolve_context.ok:
            raise job_detail_error_from_resolver(
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if result.shipment is None:
            raise job_detail_error_from_resolver(
                error_code=result.error_code or 'job_not_found',
                error_message=result.error_message,
            )
        context.shipment = result.shipment
        context.booking = result.booking
        if result.resolve_context is not None:
            context.resolver_meta = result.resolve_context.to_resolver_meta()
        if context.booking is not None and context.shipment is not None:
            pivoted = pivot_context_to_backload_booking(
                driver=context.driver,
                booking=context.booking,
                shipment=context.shipment,
                context=context,
            )
            if not pivoted:
                pivot_closed_shipment_to_active_leg(
                    driver=context.driver,
                    booking=context.booking,
                    shipment=context.shipment,
                    context=context,
                )
        return

    if context.job_type == 'booking':
        result = booking_resolver.resolve(
            context.driver,
            context.job_id,
            tenant_schema=context.tenant_schema,
        )
        if result.resolve_context is not None and not result.resolve_context.ok:
            raise job_detail_error_from_resolver(
                error_code=result.error_code,
                error_message=result.error_message,
            )
        if result.booking is None:
            raise job_detail_error_from_resolver(
                error_code=result.error_code or 'job_not_found',
                error_message=result.error_message,
            )
        context.booking = result.booking
        if result.resolve_context is not None:
            context.resolver_meta = result.resolve_context.to_resolver_meta()
        pivot_booking_to_active_shipment(
            driver=context.driver,
            booking=context.booking,
            context=context,
        )
        return

    result = movement_resolver.resolve(
        context.driver,
        context.job_id,
        tenant_schema=context.tenant_schema,
    )
    if result.resolve_context is not None and not result.resolve_context.ok:
        raise job_detail_error_from_resolver(
            error_code=result.error_code,
            error_message=result.error_message,
        )
    if result.movement is None:
        raise job_detail_error_from_resolver(
            error_code=result.error_code or 'job_not_found',
            error_message=result.error_message,
        )
    context.movement = result.movement
    if result.resolve_context is not None:
        context.resolver_meta = result.resolve_context.to_resolver_meta()
