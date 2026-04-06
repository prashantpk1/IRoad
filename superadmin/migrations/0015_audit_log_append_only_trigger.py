# PostgreSQL: enforce append-only audit log at database level (CP-PCS-P1 P11).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0014_activesession_tenant_redis_tenantprofile_bridge_key'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE OR REPLACE FUNCTION forbid_audit_log_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'security_audit_log is append-only';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS tr_forbid_audit_log_mutate ON security_audit_log;
            CREATE TRIGGER tr_forbid_audit_log_mutate
            BEFORE UPDATE OR DELETE ON security_audit_log
            FOR EACH ROW EXECUTE PROCEDURE forbid_audit_log_mutation();
            """,
            reverse_sql="""
            DROP TRIGGER IF EXISTS tr_forbid_audit_log_mutate ON security_audit_log;
            DROP FUNCTION IF EXISTS forbid_audit_log_mutation();
            """,
        ),
    ]
