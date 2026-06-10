"""Enforce tenant subscription plan caps on workspace resources."""

from __future__ import annotations

from typing import Any

from django.db import connection
from django.urls import reverse
from django_tenants.utils import schema_context

from superadmin.models import TenantProfile
from tenant_workspace.models import DriverMaster, TenantUser, TruckMaster

RESOURCE_USERS = 'users'
RESOURCE_INTERNAL_TRUCKS = 'internal_trucks'
RESOURCE_DRIVERS = 'drivers'

_RESOURCE_LABELS = {
    RESOURCE_USERS: 'users',
    RESOURCE_INTERNAL_TRUCKS: 'internal trucks',
    RESOURCE_DRIVERS: 'drivers',
}


def _effective_cap(tenant_val: int, plan_val: int | None) -> int:
    """Same rule as tenant dashboard overview."""
    tv = int(tenant_val or 0)
    if tv > 0:
        return tv
    if plan_val is None:
        return 0
    return int(plan_val)


def _is_unlimited_cap(cap: int) -> bool:
    return cap < 0


def _load_tenant_with_plan(tenant: TenantProfile) -> TenantProfile:
    prior = getattr(connection, 'tenant', None)
    connection.set_schema_to_public()
    try:
        loaded = (
            TenantProfile.objects.select_related('current_plan')
            .filter(pk=tenant.pk)
            .first()
        )
        return loaded or tenant
    finally:
        if prior is not None:
            connection.set_tenant(prior)
        else:
            connection.set_schema_to_public()


def _resource_cap(tenant: TenantProfile, resource: str) -> int:
    plan = tenant.current_plan
    if resource == RESOURCE_USERS:
        return _effective_cap(
            tenant.active_max_users,
            getattr(plan, 'max_internal_users', None) if plan else None,
        )
    if resource == RESOURCE_INTERNAL_TRUCKS:
        return _effective_cap(
            tenant.active_max_internal_trucks,
            getattr(plan, 'max_internal_trucks', None) if plan else None,
        )
    if resource == RESOURCE_DRIVERS:
        return _effective_cap(
            tenant.active_max_drivers,
            getattr(plan, 'max_active_drivers', None) if plan else None,
        )
    raise ValueError(f'Unknown subscription resource: {resource}')


def count_subscription_resource_usage(
    resource: str,
    *,
    schema_name: str | None = None,
) -> int:
    """Count current usage; caller may already be on the tenant schema."""

    def _count() -> int:
        if resource == RESOURCE_USERS:
            return TenantUser.objects.count()
        if resource == RESOURCE_INTERNAL_TRUCKS:
            return TruckMaster.active_objects.filter(
                sourcing_mode=TruckMaster.SourcingMode.IN_SOURCE,
            ).count()
        if resource == RESOURCE_DRIVERS:
            return DriverMaster.active_objects.filter(
                driver_source=DriverMaster.DriverSource.IN_SOURCE,
            ).count()
        raise ValueError(f'Unknown subscription resource: {resource}')

    if schema_name:
        with schema_context(schema_name):
            return _count()
    return _count()


def _limit_reached_message(cap: int, label: str) -> str:
    return (
        f'Your plan has only {cap} {label}. '
        'You need to upgrade or renew your plan to add more.'
    )


def subscription_limit_status(
    tenant: TenantProfile,
    resource: str,
    *,
    schema_name: str | None = None,
) -> dict[str, Any]:
    """Snapshot for templates: used/cap/allowed flags."""
    tenant = _load_tenant_with_plan(tenant)
    cap = _resource_cap(tenant, resource)
    used = count_subscription_resource_usage(resource, schema_name=schema_name)
    unlimited = _is_unlimited_cap(cap)
    allowed = unlimited or used < cap
    label = _RESOURCE_LABELS.get(resource, resource)
    show_banner = not unlimited and not allowed
    message = _limit_reached_message(cap, label) if show_banner else ''
    return {
        'resource': resource,
        'used': used,
        'cap': cap,
        'unlimited': unlimited,
        'allowed': allowed,
        'show_banner': show_banner,
        'remaining': None if unlimited else max(0, cap - used),
        'message': message,
        'upgrade_url': reverse('iroad_tenants:tenant_subscription_plan'),
    }


def check_subscription_resource_limit(
    tenant: TenantProfile,
    resource: str,
    *,
    additional: int = 1,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    """
    Return (allowed, error_message).

    ``additional`` is how many seats/slots the pending action would consume.
    """
    if additional <= 0:
        return True, None

    tenant = _load_tenant_with_plan(tenant)
    cap = _resource_cap(tenant, resource)
    if _is_unlimited_cap(cap):
        return True, None

    used = count_subscription_resource_usage(resource, schema_name=schema_name)
    if used + additional <= cap:
        return True, None

    label = _RESOURCE_LABELS.get(resource, resource)
    return False, _limit_reached_message(cap, label)


def counts_toward_internal_truck_limit(
    *,
    status: str,
    sourcing_mode: str,
) -> bool:
    return (
        status == TruckMaster.Status.ACTIVE
        and sourcing_mode == TruckMaster.SourcingMode.IN_SOURCE
    )


def counts_toward_driver_limit(
    *,
    driver_status: str,
    driver_source: str,
) -> bool:
    return (
        driver_status == DriverMaster.Status.ACTIVE
        and driver_source == DriverMaster.DriverSource.IN_SOURCE
    )
