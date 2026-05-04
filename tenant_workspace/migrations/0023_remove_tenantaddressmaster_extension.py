from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('tenant_workspace', '0022_tenant_route_master_unique_constraint'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tenantaddressmaster',
            name='extension',
        ),
    ]
