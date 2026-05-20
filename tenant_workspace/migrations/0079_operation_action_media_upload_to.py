import tenant_workspace.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0077_merge_20260518_1858'),
        ('tenant_workspace', '0078_tenantbooking_is_scheduled'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantoperationactionmedia',
            name='file',
            field=models.FileField(
                blank=True,
                default='',
                max_length=500,
                upload_to=tenant_workspace.models.operation_action_media_upload_to,
            ),
        ),
    ]
