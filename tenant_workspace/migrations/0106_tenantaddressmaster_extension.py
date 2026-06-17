from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0105_tenantclientcontractsetting_notification_audience_multiselect'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantaddressmaster',
            name='extension',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
