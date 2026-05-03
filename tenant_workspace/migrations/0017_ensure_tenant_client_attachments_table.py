# Repair: some tenant DBs recorded migrations through 0016 but never had
# tenant_client_attachments created (e.g. partial applies). Idempotent per schema.

from django.db import migrations
from django_tenants.utils import get_public_schema_name

TABLE_NAME = 'tenant_client_attachments'


def _table_exists(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = %s
            """,
            [TABLE_NAME],
        )
        return cursor.fetchone() is not None


def forwards(apps, schema_editor):
    conn = schema_editor.connection
    if getattr(conn, 'schema_name', None) == get_public_schema_name():
        return
    if _table_exists(schema_editor):
        return
    TenantClientAttachment = apps.get_model('tenant_workspace', 'TenantClientAttachment')
    schema_editor.create_model(TenantClientAttachment)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0016_merge_20260502_1209'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
