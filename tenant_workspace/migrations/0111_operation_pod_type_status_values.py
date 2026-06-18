"""Normalize POD type/status stored values to spec labels."""

from django.db import migrations, models


def forwards_pod_values(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')

    pod_type_map = {
        'Soft': 'Soft Copy',
        'Hard': 'Hard Copy',
    }
    pod_status_map = {
        'Pending': 'Not Completed',
        'Hard Copy Received': 'Not Completed',
        'Compliant': 'Completed',
        'Not Compliant': 'Not Completed',
    }

    for old, new in pod_type_map.items():
        TenantShipment.objects.filter(pod_type=old).update(pod_type=new)
        TenantBooking.objects.filter(pod_type=old).update(pod_type=new)

    for old, new in pod_status_map.items():
        TenantShipment.objects.filter(pod_status=old).update(pod_status=new)
        TenantBooking.objects.filter(pod_status=old).update(pod_status=new)


def backwards_pod_values(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')

    pod_type_map = {
        'Soft Copy': 'Soft',
        'Hard Copy': 'Hard',
    }
    pod_status_map = {
        'Completed': 'Compliant',
        'Not Completed': 'Not Compliant',
    }

    for old, new in pod_type_map.items():
        TenantShipment.objects.filter(pod_type=old).update(pod_type=new)
        TenantBooking.objects.filter(pod_type=old).update(pod_type=new)

    for old, new in pod_status_map.items():
        TenantShipment.objects.filter(pod_status=old).update(pod_status=new)
        TenantBooking.objects.filter(pod_status=old).update(pod_status=new)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0110_alter_tenantshipment_collection_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantshipment',
            name='pod_type',
            field=models.CharField(
                choices=[('Digital', 'Digital'), ('Soft Copy', 'Soft Copy'), ('Hard Copy', 'Hard Copy')],
                default='Digital',
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='tenantshipment',
            name='pod_status',
            field=models.CharField(
                choices=[('Completed', 'Completed'), ('Not Completed', 'Not Completed')],
                default='Not Completed',
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards_pod_values, backwards_pod_values),
    ]
