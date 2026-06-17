from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0104_tenantclientattachment_file_title'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantclientcontractsetting',
            name='notification_audience',
            field=models.CharField(default='System Admin', max_length=50),
        ),
    ]
