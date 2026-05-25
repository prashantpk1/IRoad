# Generated for Job Detail allowed-actions DB prefilters.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0095_job_detail_timeline_indexes_ensure'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='tenantoperationaction',
            index=models.Index(
                fields=['status', 'action_scope'],
                name='tenant_op_act_stat_scope_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantoperationaction',
            index=models.Index(
                fields=['status', 'sequence_category'],
                name='tenant_op_act_stat_cat_idx',
            ),
        ),
    ]
