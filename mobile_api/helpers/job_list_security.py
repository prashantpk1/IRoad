"""
mobile_api/helpers/job_list_security.py

Multi-tenant, driver-scoped security for the mobile job list module.

Guarantees:
- JWT ``tenant_schema`` matches request tenant context (no cross-tenant reads).
- JWT ``driver_id`` matches resolved ``DriverMaster`` row (no cross-driver sessions).
- All list ORM paths use driver-scoped querysets (IDOR-safe by construction).
- Optional outbound sanitization drops rows that fail ownership scope checks.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from django.conf import settings
from django.db.models import QuerySet
from django.utils.translation import gettext as _

from mobile_api.helpers.dashboard_ownership import (
    DriverOwnershipScope,
    preload_driver_ownership_scope,
)
from mobile_api.helpers.dashboard_security import (
    assert_movement_row_owned,
    assert_shipment_row_owned,
    driver_owns_movement_id,
    driver_owns_shipment_id,
    movement_queryset_for_driver,
    resolve_secure_dashboard_context,
    shipment_queryset_for_driver,
    validate_dashboard_tenant_binding,
)
from mobile_api.helpers.operational_status import (
    driver_movement_scope_q,
    driver_shipment_scope_q,
)
from mobile_api.rbac import get_mobile_jwt_payload

logger = logging.getLogger('mobile_api')

JOBS_API_PREFIX = '/api/v1/mobile/driver/jobs/'
JOBS_CAPABILITY = 'mobile.driver.jobs'

JobListEntityType = Literal['shipment', 'movement']


@dataclass(frozen=True)
class SecureJobListContext:
    """Bound principal for one job-list request (tenant schema + driver + scope)."""

    driver: Any
    tenant_user: Any
    tenant_schema: str
    driver_id: str
    user_id: str
    jwt_driver_id: str | None = None
    ownership_scope: DriverOwnershipScope | None = None


def validate_jobs_tenant_binding(request, *, expected_schema: str) -> bool:
    """Reject cross-tenant ``X-Tenant-ID`` / body hints on job list routes."""
    return validate_dashboard_tenant_binding(
        request,
        expected_schema=expected_schema,
    )


def jobs_ownership_sanitize_enabled() -> bool:
    return bool(
        getattr(settings, 'MOBILE_API_JOBS_ENFORCE_OWNERSHIP_SANITIZE', True)
    )


def resolve_secure_job_list_context(
    *,
    user_id: str,
    tenant_schema: str,
    request=None,
    jwt_payload: dict | None = None,
    preload_ownership: bool | None = None,
) -> dict[str, Any]:
    """
    Load tenant user + driver and enforce job-list security invariants.

    Returns ``{'success': True, 'ctx': SecureJobListContext}`` or error dict.
    """
    base = resolve_secure_dashboard_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        request=request,
        jwt_payload=jwt_payload,
    )
    if not base.get('success'):
        return base

    dash = base['ctx']
    pl = jwt_payload if jwt_payload is not None else (
        get_mobile_jwt_payload(request) if request is not None else {}
    )

    should_preload = preload_ownership
    if should_preload is None:
        should_preload = jobs_ownership_sanitize_enabled()

    scope = preload_driver_ownership_scope(dash.driver) if should_preload else None

    ctx = SecureJobListContext(
        driver=dash.driver,
        tenant_user=dash.tenant_user,
        tenant_schema=dash.tenant_schema,
        driver_id=dash.driver_id,
        user_id=dash.user_id,
        jwt_driver_id=dash.jwt_driver_id,
        ownership_scope=scope,
    )
    return {'success': True, 'ctx': ctx}


def secure_shipment_queryset_for_driver(driver) -> QuerySet:
    """
    Tenant-scoped shipments visible to this driver only.

    Filter: row ``driver_id`` OR ``booking.assigned_driver_id`` (same as dashboard).
    """
    return shipment_queryset_for_driver(driver)


def secure_movement_queryset_for_driver(driver) -> QuerySet:
    """Tenant-scoped movements where ``driver_id`` matches the authenticated driver."""
    return movement_queryset_for_driver(driver)


def assert_driver_owns_shipment(
    driver,
    shipment,
    *,
    scope: DriverOwnershipScope | None = None,
) -> bool:
    """Shipment row must belong to driver scope (IDOR guard)."""
    return assert_shipment_row_owned(driver, shipment, scope=scope)


def assert_driver_owns_movement(
    driver,
    movement,
    *,
    scope: DriverOwnershipScope | None = None,
) -> bool:
    """Movement row must belong to driver scope (IDOR guard)."""
    return assert_movement_row_owned(driver, movement, scope=scope)


def filter_owned_shipment_rows(
    rows: list,
    ctx: SecureJobListContext,
) -> list:
    """Drop shipment rows outside driver scope (defense in depth)."""
    scope = ctx.ownership_scope
    safe: list = []
    for row in rows:
        if assert_driver_owns_shipment(ctx.driver, row, scope=scope):
            safe.append(row)
        else:
            _log_ownership_violation(
                ctx,
                entity_type='shipment',
                entity_id=str(getattr(row, 'shipment_id', row.pk)),
            )
    return safe


def filter_owned_movement_rows(
    rows: list,
    ctx: SecureJobListContext,
) -> list:
    """Drop movement rows outside driver scope (defense in depth)."""
    scope = ctx.ownership_scope
    safe: list = []
    for row in rows:
        if assert_driver_owns_movement(ctx.driver, row, scope=scope):
            safe.append(row)
        else:
            _log_ownership_violation(
                ctx,
                entity_type='movement',
                entity_id=str(getattr(row, 'movement_id', row.pk)),
            )
    return safe


def sanitize_job_list_page(
    rows: list,
    *,
    ctx: SecureJobListContext,
    entity_type: JobListEntityType,
) -> list:
    """
    Outbound sanitization for paginated job cards.

    No-op when ``MOBILE_API_JOBS_ENFORCE_OWNERSHIP_SANITIZE`` is False.
    """
    if not jobs_ownership_sanitize_enabled():
        return rows
    if entity_type == 'shipment':
        return filter_owned_shipment_rows(rows, ctx)
    return filter_owned_movement_rows(rows, ctx)


def assert_job_list_action_logs_owned(
    *,
    driver,
    log_rows: list,
) -> list:
    """
    Ensure bulk-fetched action logs belong to the authenticated driver.

    Prevents IDOR if annotation/subquery were ever misconfigured.
    """
    driver_pk = getattr(driver, 'pk', None)
    safe: list = []
    for row in log_rows:
        row_driver_id = getattr(row, 'driver_id', None)
        if row_driver_id is None or row_driver_id == driver_pk:
            safe.append(row)
        else:
            logger.warning(
                'job_list_security action_log_driver_mismatch log_id=%s',
                getattr(row, 'log_id', ''),
            )
    return safe


def _log_ownership_violation(
    ctx: SecureJobListContext,
    *,
    entity_type: str,
    entity_id: str,
) -> None:
    logger.warning(
        'job_list_security ownership_violation schema=%s driver_id=%s %s=%s',
        ctx.tenant_schema,
        ctx.driver_id,
        entity_type,
        entity_id[:36],
    )
    try:
        from mobile_api.helpers.security_audit import log_mobile_security_event

        log_mobile_security_event(
            'job_list_ownership_violation',
            schema=ctx.tenant_schema,
            ip='',
            reason=f'{entity_type}:{entity_id[:64]}',
        )
    except Exception:
        pass


__all__ = [
    'JOBS_API_PREFIX',
    'JOBS_CAPABILITY',
    'SecureJobListContext',
    'assert_driver_owns_movement',
    'assert_driver_owns_shipment',
    'assert_job_list_action_logs_owned',
    'driver_movement_scope_q',
    'driver_owns_movement_id',
    'driver_owns_shipment_id',
    'driver_shipment_scope_q',
    'jobs_ownership_sanitize_enabled',
    'resolve_secure_job_list_context',
    'sanitize_job_list_page',
    'secure_movement_queryset_for_driver',
    'secure_shipment_queryset_for_driver',
    'validate_jobs_tenant_binding',
]
