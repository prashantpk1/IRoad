# Composite indexes for mobile driver dashboard activity and current-job queries.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0085_driver_mobile_notification'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['driver', '-log_date'],
                name='tenant_oal_driver_date_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(
                fields=['driver', '-updated_at'],
                name='tenant_tml_driver_upd_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(
                fields=['driver', 'status', '-updated_at'],
                name='tenant_tml_drv_stat_upd_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(
                fields=['shipment', 'status', '-updated_at'],
                name='tenant_tml_ship_stat_upd_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['driver', 'shipment_status', '-updated_at'],
                name='tenant_ship_drv_stat_upd_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentdocument',
            index=models.Index(
                fields=['shipment', 'is_delivery_note', '-updated_at'],
                name='tenant_shipdoc_ship_dn_upd_idx',
            ),
        ),
    ]
