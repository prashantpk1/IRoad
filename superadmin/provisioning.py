"""
Tenant workspace provisioning — CP section 4 / 4.3.2.

Uses django-tenants: each subscriber gets a Postgres schema and
``migrate_schemas`` for ``TENANT_APPS`` (see ``iroad_tenants.services``).
"""
import logging

logger = logging.getLogger(__name__)


def schedule_tenant_workspace_provisioning(tenant):
    """
    After ``TenantProfile`` is persisted: registry row, schema, tenant migrations.
    """
    try:
        from iroad_tenants.services import ensure_tenant_schema_registry

        ensure_tenant_schema_registry(tenant)
    except Exception:
        logger.exception(
            'Tenant schema registry failed for %s',
            tenant.tenant_id,
        )
        raise
