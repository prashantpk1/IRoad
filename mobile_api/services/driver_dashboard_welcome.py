"""
mobile_api/services/driver_dashboard_welcome.py

Lightweight welcome header projections for the driver home dashboard.

Does not call ``get_driver_profile`` or the full profile serializers — only
uses rows already loaded by ``load_driver_welcome_context``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings as django_settings

from mobile_api.helpers.i18n import SUPPORTED_LANGUAGES, get_localized_value, get_request_language
from mobile_api.serializers.driver_profile import safe_media_url
from mobile_api.serializers.localized import serialize_localized_field
from mobile_api.services.driver_dashboard_context import DriverWelcomeContext


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace('+00:00', 'Z')


def project_welcome_driver_profile(
    *,
    driver,
    ctx: DriverWelcomeContext,
) -> dict[str, Any]:
    return {
        'driver_id': str(driver.driver_id),
        'driver_code': driver.driver_code or '',
        'name': ctx.name,
        'profile_photo_url': ctx.profile_photo_url,
        'driver_status': driver.driver_status or '',
        'driver_type': str(driver.driver_type or ''),
    }


def project_welcome_role(*, tenant_user) -> dict[str, Any]:
    return {
        'role_name': getattr(tenant_user, 'role_name', '') or '',
        'user_status': getattr(tenant_user, 'status', '') or '',
    }


def project_welcome_organization(
    *,
    ctx: DriverWelcomeContext,
    request=None,
) -> dict[str, Any]:
    org_row = ctx.org_profile
    org_name = ctx.organization_name
    logo_url = ''
    if org_row is not None:
        name_part = serialize_localized_field(
            request,
            getattr(org_row, 'name_en', None),
            getattr(org_row, 'name_ar', None),
            field_name='organization_name',
        )
        org_name = name_part.get('organization_name') or org_name
        logo_url = safe_media_url(request, getattr(org_row, 'logo_file', None)) or ''

    return {
        'tenant_id': ctx.tenant_id,
        'schema_name': ctx.schema_name,
        'organization_name': org_name,
        'company_name': ctx.company_name or '',
        'logo_url': logo_url,
    }


def project_welcome_assigned_truck(
    *,
    truck,
    request=None,
) -> dict[str, Any] | None:
    if truck is None:
        return None

    truck_type = getattr(truck, 'truck_type', None)
    type_label = ''
    if truck_type is not None:
        type_label = get_localized_value(
            request,
            getattr(truck_type, 'english_label', '') or '',
            getattr(truck_type, 'arabic_label', '') or '',
        )

    return {
        'truck_id': str(truck.truck_id),
        'truck_code': truck.truck_code or '',
        'plate_number': truck.plate_number or '',
        'truck_status': getattr(truck, 'status', None),
        'sourcing_mode': getattr(truck, 'sourcing_mode', None),
        'truck_type_label': type_label,
    }


def project_welcome_current_assignment(*, assignment) -> dict[str, Any] | None:
    if assignment is None:
        return None
    return {
        'assignment_id': str(assignment.assignment_id),
        'assigned_from': _iso_dt(assignment.assigned_from),
        'assigned_to': _iso_dt(assignment.assigned_to),
        'assignment_status': assignment.assignment_status,
        'is_current': assignment.assigned_to is None,
    }


def project_welcome_locale(*, request=None, org_profile) -> dict[str, Any]:
    tz = getattr(django_settings, 'TIME_ZONE', 'UTC')
    sys_lang = 'en'
    date_fmt = 'DD/MM/YYYY'
    num_fmt = '1,234.56'
    neg_fmt = '-100'
    if org_profile is not None:
        sys_lang = getattr(org_profile, 'system_language', None) or 'en'
        tz = getattr(org_profile, 'timezone', None) or tz
        date_fmt = getattr(org_profile, 'date_format', None) or date_fmt
        num_fmt = getattr(org_profile, 'number_format', None) or num_fmt
        neg_fmt = getattr(org_profile, 'negative_format', None) or neg_fmt

    return {
        'request_language': get_request_language(request),
        'supported_languages': sorted(SUPPORTED_LANGUAGES),
        'timezone': tz,
        'system_language': sys_lang,
        'date_format': date_fmt,
        'number_format': num_fmt,
        'negative_format': neg_fmt,
    }


def project_welcome_operational_context(
    *,
    driver,
    ctx: DriverWelcomeContext,
    counters: dict[str, int] | None = None,
) -> dict[str, Any]:
    assignment = ctx.assignment
    truck = ctx.truck
    assignment_status = assignment.assignment_status if assignment else None
    counter_block: dict[str, int] = {}
    if counters:
        from mobile_api.services.driver_dashboard_counters import (
            build_dashboard_counters_snapshot,
        )

        counter_block = build_dashboard_counters_snapshot(counters)

    return {
        'tenant_schema': ctx.schema_name,
        'driver_assignment_required': ctx.driver_assignment_required,
        'has_assigned_truck': truck is not None,
        'has_current_assignment': assignment is not None and assignment.assigned_to is None,
        'driver_status': driver.driver_status or '',
        'assignment_status': assignment_status,
        'counters_snapshot': counter_block or None,
    }


def build_dashboard_welcome(
    *,
    driver,
    tenant_user,
    ctx: DriverWelcomeContext,
    request=None,
    counters: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Assemble nested welcome DTO plus flat aliases for existing mobile clients.
    """
    driver_block = project_welcome_driver_profile(driver=driver, ctx=ctx)
    role_block = project_welcome_role(tenant_user=tenant_user)
    organization_block = project_welcome_organization(ctx=ctx, request=request)
    truck_block = project_welcome_assigned_truck(truck=ctx.truck, request=request)
    assignment_block = project_welcome_current_assignment(assignment=ctx.assignment)
    locale_block = project_welcome_locale(request=request, org_profile=ctx.org_profile)
    operational_block = project_welcome_operational_context(
        driver=driver,
        ctx=ctx,
        counters=counters,
    )

    display_name = {
        'name': driver_block['name'],
        'name_en': (driver.english_name or '').strip(),
        'name_ar': (driver.arabic_name or '').strip(),
    }

    flat: dict[str, Any] = {
        'driver_id': driver_block['driver_id'],
        'driver_code': driver_block['driver_code'],
        'name': driver_block['name'],
        'profile_photo_url': driver_block['profile_photo_url'],
        'role_name': role_block['role_name'],
        'organization_name': organization_block['organization_name'],
        'tenant_id': organization_block['tenant_id'],
        'schema_name': organization_block['schema_name'],
        'assigned_truck': truck_block,
        'assignment_status': operational_block['assignment_status'],
        'plate_number': (truck_block or {}).get('plate_number') or '',
        'display_name': display_name,
    }

    return {
        **flat,
        'driver': driver_block,
        'role': role_block,
        'organization': organization_block,
        'assigned_truck': truck_block,
        'current_assignment': assignment_block,
        'locale': locale_block,
        'operational_context': operational_block,
    }
