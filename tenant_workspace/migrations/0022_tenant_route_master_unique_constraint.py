from django.db import migrations


class Migration(migrations.Migration):
    """
    Some tenant schemas have tenant_route_master without the unique constraint
    (e.g. table created outside the stock 0021 migration). Add it idempotently.
    """

    dependencies = [
        ('tenant_workspace', '0021_tenantroutemaster'),
    ]

    operations = [
        migrations.RunSQL(
            sql=r"""
            DO $body$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON c.conrelid = t.oid
                    JOIN pg_namespace n ON t.relnamespace = n.oid
                    WHERE c.conname = 'tenant_route_type_origin_destination_uq'
                      AND t.relname = 'tenant_route_master'
                      AND n.nspname = current_schema()
                ) THEN
                    ALTER TABLE tenant_route_master
                    ADD CONSTRAINT tenant_route_type_origin_destination_uq
                    UNIQUE (route_type, origin_location_id, destination_location_id);
                END IF;
            END
            $body$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
