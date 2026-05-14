import django.db.models.deletion
from django.db import migrations, models


def backfill_existing_round_booking_backload_lines(apps, schema_editor):
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    TenantBooking.objects.filter(
        trip_type='Round',
        booking_line_backload_truck__isnull=True,
        booking_line_backload_driver__isnull=True,
        booking_line_backload_cod_amount=0,
        booking_line_backload_pod_doc_count=0,
    ).update(
        booking_line_backload_truck=models.F('assigned_truck'),
        booking_line_backload_driver=models.F('assigned_driver'),
        booking_line_backload_cod_amount=models.F('booking_line_cod_amount'),
        booking_line_backload_pod_doc_count=models.F('booking_line_pod_doc_count'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0056_tenantshipmentsurcharge_transaction_no'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantbooking',
            name='booking_line_backload_cod_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='booking_line_backload_driver',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='backload_assigned_bookings',
                to='tenant_workspace.drivermaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='booking_line_backload_pod_doc_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='booking_line_backload_truck',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='backload_assigned_bookings',
                to='tenant_workspace.truckmaster',
            ),
        ),
        migrations.RunPython(
            backfill_existing_round_booking_backload_lines,
            migrations.RunPython.noop,
        ),
    ]
