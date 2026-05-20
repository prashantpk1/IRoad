# Index for dashboard latest-action lookup (one row per active shipment).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0083_dashboard_driver_counter_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['shipment', 'driver', '-log_date'],
                name='tenant_oal_ship_drv_date_idx',
            ),
        ),
    ]
