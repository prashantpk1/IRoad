"""
Ensure Job Detail timeline cursor indexes exist (idempotent per schema).

Tenants that applied a broken 0094 (RemoveIndex) before the fix need this
migration to restore indexes without failing on schemas that already have them.
"""

from __future__ import annotations

from django.db import migrations, models


TIMELINE_INDEXES = (
    (
        'tenant_oal_ship_drv_dt_id_idx',
        ['shipment', 'driver', '-log_date', '-log_id'],
    ),
    (
        'tenant_oal_move_drv_dt_id_idx',
        ['truck_movement', 'driver', '-log_date', '-log_id'],
    ),
    (
        'tenant_oal_ship_created_idx',
        ['shipment', '-created_at'],
    ),
    (
        'tenant_oal_move_created_idx',
        ['truck_movement', '-created_at'],
    ),
)


def _index_names_on_table(connection, table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = ANY (current_schemas(false))
              AND tablename = %s
            """,
            [table_name],
        )
        return {row[0] for row in cursor.fetchall()}


def ensure_timeline_indexes(apps, schema_editor):
    TenantOperationActionLog = apps.get_model('tenant_workspace', 'TenantOperationActionLog')
    table = TenantOperationActionLog._meta.db_table
    existing = _index_names_on_table(schema_editor.connection, table)
    for name, fields in TIMELINE_INDEXES:
        if name in existing:
            continue
        schema_editor.add_index(
            TenantOperationActionLog,
            models.Index(fields=fields, name=name),
        )


def remove_timeline_indexes_if_present(apps, schema_editor):
    TenantOperationActionLog = apps.get_model('tenant_workspace', 'TenantOperationActionLog')
    table = TenantOperationActionLog._meta.db_table
    existing = _index_names_on_table(schema_editor.connection, table)
    for name, fields in reversed(TIMELINE_INDEXES):
        if name not in existing:
            continue
        schema_editor.remove_index(
            TenantOperationActionLog,
            models.Index(fields=fields, name=name),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0094_remove_tenantoperationactionlog_tenant_oal_ship_drv_dt_id_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(ensure_timeline_indexes, remove_timeline_indexes_if_present),
    ]
