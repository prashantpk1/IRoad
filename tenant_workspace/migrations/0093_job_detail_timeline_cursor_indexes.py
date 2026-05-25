# Cursor-friendly composite indexes for mobile job detail timelines.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0092_merge_20260525_1140'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['shipment', 'driver', '-log_date', '-log_id'],
                name='tenant_oal_ship_drv_dt_id_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['truck_movement', 'driver', '-log_date', '-log_id'],
                name='tenant_oal_move_drv_dt_id_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['shipment', '-created_at'],
                name='tenant_oal_ship_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['truck_movement', '-created_at'],
                name='tenant_oal_move_created_idx',
            ),
        ),
    ]
