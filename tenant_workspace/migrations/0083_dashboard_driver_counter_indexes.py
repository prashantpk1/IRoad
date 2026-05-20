# Generated for mobile driver dashboard counter aggregates.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0082_merge_20260520_1537'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantbooking',
            index=models.Index(
                fields=['assigned_driver'],
                name='tenant_book_assign_drv_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['driver', 'shipment_status'],
                name='tenant_ship_driver_status_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['driver', 'updated_at'],
                name='tenant_ship_driver_upd_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['booking', 'shipment_status'],
                name='tenant_ship_book_stat_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['shipment_status', 'pod_status'],
                name='tenant_ship_stat_pod_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['shipment_status', 'collection_status'],
                name='tenant_ship_stat_coll_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(
                fields=['driver', 'status'],
                name='tenant_tml_driver_status_idx',
            ),
        ),
    ]
