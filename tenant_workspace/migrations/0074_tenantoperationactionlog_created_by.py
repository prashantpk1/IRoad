import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0073_tenantoperationactionlog_and_media'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantoperationactionlog',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='operation_action_logs_created',
                to='tenant_workspace.tenantuser',
            ),
        ),
    ]
