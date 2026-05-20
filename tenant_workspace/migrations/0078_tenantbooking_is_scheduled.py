from django.db import migrations, models


def backfill_is_scheduled(apps, schema_editor):
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    for booking in TenantBooking.objects.all().iterator():
        if (
            booking.booking_date
            and booking.creation_date
            and booking.booking_date > booking.creation_date
        ):
            booking.is_scheduled = True
            booking.save(update_fields=['is_scheduled'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0077_shipment_status_loaded_lifecycle'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantbooking',
            name='is_scheduled',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_is_scheduled, migrations.RunPython.noop),
    ]
