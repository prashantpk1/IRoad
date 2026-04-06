"""
Create/sync ``TenantRegistry`` + tenant schema migrations (django-tenants).
"""
import logging

from django.core.management import call_command
from django.db import connection

logger = logging.getLogger(__name__)


def default_workspace_schema_name(tenant_profile):
    return f't_{str(tenant_profile.tenant_id).replace("-", "").lower()}'


def ensure_tenant_schema_registry(tenant_profile):
    """
    Ensure ``TenantRegistry`` exists, Postgres schema exists, and
    ``TENANT_APPS`` migrations are applied for that schema.

    Safe to call when schema was created earlier via raw SQL: runs
    ``migrate_schemas`` for the tenant so workspace tables are created.
    """
    from superadmin.models import TenantProfile

    connection.set_schema_to_public()

    name = (tenant_profile.workspace_schema or '').strip()
    if not name:
        name = default_workspace_schema_name(tenant_profile)
        TenantProfile.objects.filter(pk=tenant_profile.pk).update(
            workspace_schema=name,
        )
        tenant_profile.workspace_schema = name

    from iroad_tenants.models import TenantRegistry, TenantSite

    reg, _created = TenantRegistry.objects.get_or_create(
        tenant_profile_id=tenant_profile.pk,
        defaults={'schema_name': name},
    )
    if reg.schema_name != name:
        logger.warning(
            'TenantRegistry schema_name=%s differs from profile workspace_schema=%s '
            'for tenant %s; keeping registry name.',
            reg.schema_name,
            name,
            tenant_profile.tenant_id,
        )
        TenantProfile.objects.filter(pk=tenant_profile.pk).update(
            workspace_schema=reg.schema_name,
        )
        name = reg.schema_name

    domain_name = f'{tenant_profile.tenant_id}.iroad.internal'
    TenantSite.objects.get_or_create(
        tenant=reg,
        domain=domain_name,
        defaults={'is_primary': True},
    )

    try:
        call_command(
            'migrate_schemas',
            tenant=True,
            schema_name=name,
            interactive=False,
            verbosity=0,
        )
    except Exception:
        logger.exception(
            'migrate_schemas failed for tenant schema %s',
            name,
        )
        raise
