"""
mobile_api/job_detail/services/booking_job_resolver.py

Resolve an explicit **booking job** by id with driver ownership checks.

Used when Auto Shipment is enabled but no shipment exists yet (pre-A4 bootstrap).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from mobile_api.job_detail.dto.job_resolve_context import (
    JobResolveContext,
    WORKFLOW_SOURCE_ENTITY_RESOLVER,
)
from mobile_api.job_detail.guards.entity_lookup import (
    booking_entity_summary,
    lookup_booking_by_reference,
)
from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    booking_is_driver_accessible,
    driver_owns_booking,
)


@dataclass(frozen=True)
class BookingJobResolveResult:
    booking: Any | None
    resolve_context: JobResolveContext | None = None
    error_message: str | None = None
    error_code: str | None = None


def resolve_booking_job(
    driver: Any,
    booking_id: str,
    *,
    tenant_schema: str,
) -> JobResolveContext:
    """Resolve one booking job inside the JWT tenant schema with ownership validation."""
    schema = (tenant_schema or '').strip()
    if not schema:
        return JobResolveContext(
            job_type='booking',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code='tenant_required',
            error_message=str(_('mobile.auth.tenant_required')),
        )

    driver_err = assert_driver_active(driver)
    if driver_err:
        return JobResolveContext(
            job_type='booking',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code=driver_err,
            error_message=str(_('mobile.auth.driver_inactive')),
        )

    reference = (booking_id or '').strip()
    if not reference:
        return JobResolveContext(
            job_type='booking',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code='invalid_job_reference',
            error_message=str(_('mobile.validation.failed')),
        )

    with schema_context(schema):
        booking = lookup_booking_by_reference(reference)
        if booking is None:
            return JobResolveContext(
                job_type='booking',
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='job_not_found',
                error_message=str(_('mobile.jobs.not_found')),
            )
        if not booking_is_driver_accessible(booking):
            return JobResolveContext(
                job_type='booking',
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='job_inactive',
                error_message=str(_('mobile.jobs.inactive')),
            )
        if not driver_owns_booking(driver, booking):
            return JobResolveContext(
                job_type='booking',
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='forbidden',
                error_message=str(_('mobile.auth.forbidden')),
            )

        entity = booking_entity_summary(booking)
        return JobResolveContext(
            job_type='booking',
            entity=entity,
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=True,
            entity_row=booking,
            booking=booking,
        )


class BookingJobResolver:
    """Class wrapper for dependency injection in context / execution services."""

    def resolve(
        self,
        driver: Any,
        booking_id: str,
        *,
        tenant_schema: str,
    ) -> BookingJobResolveResult:
        ctx = resolve_booking_job(driver, booking_id, tenant_schema=tenant_schema)
        if not ctx.ok:
            return BookingJobResolveResult(
                booking=None,
                resolve_context=ctx,
                error_message=ctx.error_message,
                error_code=ctx.error_code,
            )
        return BookingJobResolveResult(
            booking=ctx.entity_row,
            resolve_context=ctx,
        )
