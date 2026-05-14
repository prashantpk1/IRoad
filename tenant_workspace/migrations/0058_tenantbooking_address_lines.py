import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0057_tenantbooking_backload_line_values'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantbooking',
            name='delivery_address',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='delivery_bookings',
                to='tenant_workspace.tenantaddressmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='delivery_booking_item',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='loading_address',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='loading_bookings',
                to='tenant_workspace.tenantaddressmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantbooking',
            name='loading_booking_item',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
