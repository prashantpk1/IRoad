from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0079_operation_action_media_upload_to'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantoperationactionlog',
            name='idempotency_key',
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
    ]

