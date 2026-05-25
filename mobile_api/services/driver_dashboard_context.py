"""
mobile_api/services/driver_dashboard_context.py

One-shot tenant-scoped reads shared by dashboard welcome and driver_summary.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mobile_api.serializers.driver_profile import safe_media_url
from mobile_api.serializers.localized import serialize_localized_name

logger = logging.getLogger('mobile_api')

_ORG_PROFILE_ONLY = (
    'id',
    'name_en',
    'name_ar',
    'logo_file',
    'timezone',
    'system_language',
    'date_format',
    'number_format',
    'negative_format',
)


@dataclass
class DriverWelcomeContext:
    """Cached rows for welcome header + compact driver_summary."""

    assignment: Any
    truck: Any
    org_profile: Any
    organization_name: str
    company_name: str
    tenant_id: str
    tenant_profile_id: str | None
    schema_name: str
    name: str
    profile_photo_url: str | None
    driver_assignment_required: bool


# Backward-compatible alias
DashboardShellContext = DriverWelcomeContext


def load_driver_welcome_context(
    *,
    driver,
    tenant_user,
    tenant_schema: str,
    request=None,
) -> DriverWelcomeContext:
    from iroad_tenants.models import TenantRegistry
    from tenant_workspace.models import (
        DriverSettings,
        OrganizationProfile,
        TruckDriverAssignmentHistory,
    )

    assignment = (
        TruckDriverAssignmentHistory.objects.filter(
            driver=driver,
            assigned_to__isnull=True,
        )
        .select_related('truck', 'truck__truck_type')
        .order_by('-assigned_from', '-created_at')
        .first()
    )
    truck = assignment.truck if assignment else None

    org_name = ''
    company_name = ''
    tenant_id = ''
    tenant_profile_id = None
    reg = (
        TenantRegistry.objects.select_related('tenant_profile')
        .filter(schema_name=tenant_schema)
        .first()
    )
    if reg and reg.tenant_profile:
        tenant_profile_id = str(reg.tenant_profile_id)
        tenant_id = tenant_profile_id
        company_name = reg.tenant_profile.company_name or ''
        org_name = company_name

    org_row = (
        OrganizationProfile.objects.only(*_ORG_PROFILE_ONLY)
        .order_by('-updated_at', '-created_at')
        .first()
    )
    if org_row is not None:
        from mobile_api.helpers.i18n import get_localized_value

        org_name = get_localized_value(
            request,
            getattr(org_row, 'name_en', '') or org_name,
            getattr(org_row, 'name_ar', '') or '',
        ) or org_name

    driver_assignment_required = False
    try:
        settings_row = (
            DriverSettings.objects.only('driver_assignment_required')
            .order_by('settings_id')
            .first()
        )
        if settings_row is not None:
            driver_assignment_required = bool(settings_row.driver_assignment_required)
    except Exception as exc:
        logger.debug('DriverSettings read failed: %s', exc)

    name_block = serialize_localized_name(
        request,
        english_value=driver.english_name or '',
        arabic_value=driver.arabic_name,
    )

    return DriverWelcomeContext(
        assignment=assignment,
        truck=truck,
        org_profile=org_row,
        organization_name=org_name,
        company_name=company_name,
        tenant_id=tenant_id,
        tenant_profile_id=tenant_profile_id,
        schema_name=tenant_schema,
        name=name_block.get('name') or '',
        profile_photo_url=safe_media_url(request, driver.dl_image),
        driver_assignment_required=driver_assignment_required,
    )


def load_dashboard_shell(
    *,
    driver,
    tenant_user,
    tenant_schema: str,
    request=None,
) -> DriverWelcomeContext:
    """Alias for ``load_driver_welcome_context`` (legacy dashboard service name)."""
    return load_driver_welcome_context(
        driver=driver,
        tenant_user=tenant_user,
        tenant_schema=tenant_schema,
        request=request,
    )
