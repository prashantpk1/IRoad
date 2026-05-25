# Index for batched latest-action lookup on movement job list cards.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0088_job_list_search_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(
                fields=['truck_movement', 'driver', '-log_date'],
                name='tenant_oal_move_drv_date_idx',
            ),
        ),
    ]
