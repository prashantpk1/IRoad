from django.db import migrations, models

import tenant_workspace.models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0081_tenantoperationactionlog_source_channel_ref'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantbooking',
            name='booking_attachment',
            field=models.FileField(
                blank=True,
                max_length=500,
                null=True,
                upload_to=tenant_workspace.models.booking_attachment_upload_to,
            ),
        ),
    ]
