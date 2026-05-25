# Indexed operational rank for mobile job list priority_desc sorting.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0089_job_list_movement_action_log_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipment',
            name='mobile_operational_rank',
            field=models.SmallIntegerField(db_index=True, default=10),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(
                fields=['driver', 'mobile_operational_rank', '-updated_at'],
                name='tenant_ship_drv_rank_upd_idx',
            ),
        ),
    ]
