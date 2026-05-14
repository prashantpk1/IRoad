"""
mobile_api/services/driver_organization_profile_service.py

Tenant organization profile (support + branding) for the authenticated driver.

See ``mobile_api/docs/driver_organization_profile.md`` for API usage notes.

Views must call these helpers — no ORM in views.
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils.translation import gettext as _
from django_tenants.utils import schema_context

from mobile_api.serializers.driver_organization_profile import (
    DriverOrganizationProfileSerializer,
)
from mobile_api.services.driver_profile_service import _resolve_driver_context

from tenant_workspace.models import OrganizationProfile

logger = logging.getLogger('mobile_api')


def get_driver_organization_profile(
    *,
    tenant_schema: str,
    user_id: str,
    request=None,
    jwt_payload: dict | None = None,
) -> dict[str, Any]:
    """
    Return serialized organization profile for the driver's tenant.

    Reuses ``_resolve_driver_context`` (same TenantUser / DriverMaster / JWT
    guards as ``get_driver_profile``).

    Loads the latest ``OrganizationProfile`` row for the tenant schema (no FK
    from driver). If no row exists, returns a controlled error dict.

    Serialized payload uses ``DriverOrganizationProfileSerializer``: localized
    ``organization_name`` from ``Accept-Language``; ``driver_instructions`` is
    one DB field (same for all languages); null-safe strings and ``logo_url``.

    Returns:
        {'success': True, 'organization_profile': <dict>}
        {'success': False, 'error': lazy_str}
    """
    jwt_email = (jwt_payload or {}).get('email')
    ctx = _resolve_driver_context(
        user_id=user_id,
        tenant_schema=tenant_schema,
        jwt_email=jwt_email,
    )
    if not ctx['success']:
        return {'success': False, 'error': ctx['error']}

    try:
        with schema_context(tenant_schema):
            org = (
                OrganizationProfile.objects.order_by(
                    '-updated_at',
                    '-created_at',
                ).first()
            )
            if org is None:
                logger.warning(
                    'organization profile missing schema=%s user_id=%s',
                    tenant_schema,
                    user_id,
                )
                return {
                    'success': False,
                    'error': _('mobile.error.not_found'),
                }

            data = DriverOrganizationProfileSerializer(
                instance=org,
                context={'request': request},
            ).data
    except Exception as exc:
        logger.error(
            'get_driver_organization_profile error schema=%s user_id=%s: %s',
            tenant_schema,
            user_id,
            exc,
        )
        return {
            'success': False,
            'error': _('mobile.validation.failed'),
        }

    return {'success': True, 'organization_profile': data}
