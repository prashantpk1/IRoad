"""
mobile_api/job_detail/services/movement_job_resolver.py

Resolve an explicit **empty move** (movement-only job) by id with driver ownership checks.
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
    lookup_movement_by_reference,
    movement_entity_summary,
)
from mobile_api.job_detail.guards.ownership import (
    assert_driver_active,
    driver_owns_movement,
    movement_is_driver_accessible,
    movement_is_empty_move_job,
)


@dataclass(frozen=True)
class MovementJobResolveResult:
    """Legacy/class wrapper result — prefer ``JobResolveContext`` from ``resolve_empty_move_job``."""

    movement: Any | None
    resolve_context: JobResolveContext | None = None
    error_message: str | None = None
    error_code: str | None = None


def resolve_empty_move_job(
    driver: Any,
    movement_id: str,
    *,
    tenant_schema: str,
) -> JobResolveContext:
    """
    Resolve one empty-move job inside the JWT tenant schema with ownership validation.

    Args:
        driver: Authenticated ``DriverMaster``.
        movement_id: ``movement_id`` UUID or ``movement_no``.
        tenant_schema: JWT ``tenant_schema``.

    Returns:
        ``JobResolveContext`` with ``ownership_validated=True`` on success.
    """
    schema = (tenant_schema or '').strip()
    if not schema:
        return JobResolveContext(
            job_type='movement',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code='tenant_required',
            error_message=str(_('mobile.auth.tenant_required')),
        )

    driver_err = assert_driver_active(driver)
    if driver_err:
        return JobResolveContext(
            job_type='movement',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code=driver_err,
            error_message=str(_('mobile.auth.driver_inactive')),
        )

    reference = (movement_id or '').strip()
    if not reference:
        return JobResolveContext(
            job_type='movement',
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=False,
            error_code='invalid_job_reference',
            error_message=str(_('mobile.validation.failed')),
        )

    with schema_context(schema):
        movement = lookup_movement_by_reference(reference)
        if movement is None:
            return JobResolveContext(
                job_type='movement',
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='job_not_found',
                error_message=str(_('mobile.jobs.not_found')),
            )

        if not movement_is_empty_move_job(movement):
            return JobResolveContext(
                job_type='movement',
                entity=movement_entity_summary(movement),
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='not_empty_move',
                error_message=str(_('mobile.jobs.not_empty_move')),
            )

        if not movement_is_driver_accessible(movement):
            return JobResolveContext(
                job_type='movement',
                entity=movement_entity_summary(movement),
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='job_inactive',
                error_message=str(_('mobile.jobs.inactive')),
            )

        if not driver_owns_movement(driver, movement):
            return JobResolveContext(
                job_type='movement',
                entity=movement_entity_summary(movement),
                workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
                ownership_validated=False,
                error_code='forbidden',
                error_message=str(_('mobile.auth.forbidden')),
            )

        return JobResolveContext(
            job_type='movement',
            entity=movement_entity_summary(movement),
            workflow_source=WORKFLOW_SOURCE_ENTITY_RESOLVER,
            ownership_validated=True,
            entity_row=movement,
        )


class MovementJobResolver:
    """Class adapter for ``JobDetailContextService`` injection."""

    def resolve(
        self,
        driver: Any,
        job_id: str,
        *,
        tenant_schema: str,
    ) -> MovementJobResolveResult:
        ctx = resolve_empty_move_job(
            driver,
            job_id,
            tenant_schema=tenant_schema,
        )
        if not ctx.ok:
            return MovementJobResolveResult(
                movement=None,
                resolve_context=ctx,
                error_message=ctx.error_message,
                error_code=ctx.error_code,
            )
        return MovementJobResolveResult(
            movement=ctx.entity_row,
            resolve_context=ctx,
            error_message=None,
            error_code=None,
        )
