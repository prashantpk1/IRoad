from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0059_tenantshipmentdocument_pod_truck_driver_display'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tenantshipmentdocument',
            name='pod_driver_display',
        ),
        migrations.RemoveField(
            model_name='tenantshipmentdocument',
            name='pod_truck_display',
        ),
    ]
