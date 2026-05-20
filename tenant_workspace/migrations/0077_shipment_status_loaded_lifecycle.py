# Generated for IRoute Ch.4 shipment lifecycle (Loaded birth state).

from django.db import migrations, models


def migrate_created_to_loaded(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantShipment.objects.filter(shipment_status='Created').update(shipment_status='Loaded')


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0076_remove_tenanttruckmovementlog_movement_type'),
        ('tenant_workspace', '0068_alter_tenantshipmentdocument_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantshipment',
            name='shipment_status',
            field=models.CharField(
                choices=[
                    ('Loaded', 'Loaded'),
                    ('In Transit', 'In Transit'),
                    ('At Delivery', 'At Delivery'),
                    ('POD Submitted', 'POD Submitted'),
                    ('Delivered', 'Delivered'),
                    ('Closed', 'Closed'),
                    ('Cancelled', 'Cancelled'),
                    ('Created', 'Created'),
                ],
                default='Loaded',
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_created_to_loaded, migrations.RunPython.noop),
    ]
