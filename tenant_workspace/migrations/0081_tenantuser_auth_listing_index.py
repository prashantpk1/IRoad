# Supports common filters on active/inactive + soft-delete (admin, reporting, auth-adjacent paths).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0080_tenantuser_mobile_login_audit_fields'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantuser',
            index=models.Index(
                fields=['is_deleted', 'status'],
                name='tu_deleted_status_idx',
            ),
        ),
    ]
