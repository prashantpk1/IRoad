"""
mobile_api/job_detail/services/shipment_job_resolver.py

Resolve an explicit **shipment job** by id with driver ownership checks.

NOT a "current job" selector — caller supplies ``shipment_id`` from list/navigation.
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
    lookup_shipment_by_reference,
    shipment_entity_summary,
)
from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    driver_owns_shipment_leg,
    shipment_is_driver_accessible,
)


@dataclass(frozen=True)
class ShipmentJobResolveResult:
    """Legacy/class wrapper result — prefer ``JobResolveContext`` from ``resolve_shipment_job``."""

    shipment: Any | None
    booking: Any | None
    resolve_context: JobResolveContext | None = None
    error_message: str | None = None
    error_code: str | None = None


def resolve_shipment_job(
    driver: Any,
    shipment_id: str,
    *,
    tenant_schema: str,
) -> JobResolveContext:
    """
    Resolve one shipment job inside the JWT tenant schema with ownership validation.

    Args:
        driver: Authenticated ``DriverMaster`` (from mobile session).
        shipment_id: ``shipment_id`` UUID or ``shipment_no``.
        tenant_schema: JWT ``tenant_schema`` — required for tenant isolation.

    Returns:
        ``JobResolveContext`` with ``ownership_validated=True`` on success.
    """
    schema = (tenant_schema or '').strip()
    if not schema:
        return JobResolveContext(
            job_type='shipment',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code='tenant_required',
            error_message=str(_('mobile.auth.tenant_required')),
        )

    driver_err = assert_driver_active(driver)
    if driver_err:
        return JobResolveContext(
            job_type='shipment',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code=driver_err,
            error_message=str(_('mobile.auth.driver_inactive')),
        )

    reference = (shipment_id or '').strip()
    if not reference:
        return JobResolveContext(
            job_type='shipment',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code='invalid_job_reference',
            error_message=str(_('mobile.validation.failed')),
        )

    with schema_context(schema):
        shipment = lookup_shipment_by_reference(reference)
        if shipment is None:
            return JobResolveContext(
                job_type='shipment',
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='job_not_found',
                error_message=str(_('mobile.jobs.not_found')),
            )

        if not shipment_is_driver_accessible(shipment):
            return JobResolveContext(
                job_type='shipment',
                entity=shipment_entity_summary(shipment),
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='job_inactive',
                error_message=str(_('mobile.jobs.inactive')),
            )

        booking = getattr(shipment, 'booking', None)
        if not driver_owns_shipment_leg(driver, booking, shipment):
            return JobResolveContext(
                job_type='shipment',
                entity=shipment_entity_summary(shipment),
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='forbidden',
                error_message=str(_('mobile.auth.forbidden')),
            )

        return JobResolveContext(
            job_type='shipment',
            entity=shipment_entity_summary(shipment),
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=True,
            entity_row=shipment,
            shipment=shipment,
            booking=booking,
        )


class ShipmentJobResolver:
    """Class adapter for ``JobDetailContextService`` injection."""

    def resolve(
        self,
        driver: Any,
        job_id: str,
        *,
        tenant_schema: str,
    ) -> ShipmentJobResolveResult:
        ctx = resolve_shipment_job(
            driver,
            job_id,
            tenant_schema=tenant_schema,
        )
        if not ctx.ok:
            return ShipmentJobResolveResult(
                shipment=None,
                booking=None,
                resolve_context=ctx,
                error_message=ctx.error_message,
                error_code=ctx.error_code,
            )
        return ShipmentJobResolveResult(
            shipment=ctx.entity_row,
            booking=ctx.booking,
            resolve_context=ctx,
            error_message=None,
            error_code=None,
        )
