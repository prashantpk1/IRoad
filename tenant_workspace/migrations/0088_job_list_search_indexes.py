# Composite indexes for mobile driver job list search and empty-move filters.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0087_alter_drivermobilenotification_dedupe_key_and_more'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['driver', 'shipment_no'],
                name='tenant_ship_drv_no_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(
                fields=['driver', 'movement_no'],
                name='tenant_tml_drv_mno_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(
                fields=['driver', 'movement_source'],
                name='tenant_tml_drv_src_idx',
            ),
        ),
    ]
