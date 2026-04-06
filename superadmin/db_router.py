"""
Database routing (Phase 1: single ``default`` database connection).

Each ``TenantProfile`` may have ``workspace_schema`` (PostgreSQL schema
created via ``provisioning.ensure_postgres_workspace_schema``). ORM models
still live in ``public``; route tenant-operational tables to the per-tenant
schema in Phase 2 (e.g. ``search_path`` or secondary app config).
"""


class MasterDataRouter:
    """
    No-op router: all models use ``default``.

    Phase 2: return ``tenant_{uuid}`` connection alias for tenant-specific apps.
    """

    def db_for_read(self, model, **hints):
        return None

    def db_for_write(self, model, **hints):
        return None

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return None
