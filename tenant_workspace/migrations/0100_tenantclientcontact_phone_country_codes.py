from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0099_merge_20260528_1524'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantclientcontact',
            name='mobile_country_code',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
        migrations.AddField(
            model_name='tenantclientcontact',
            name='telephone_country_code',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
    ]
