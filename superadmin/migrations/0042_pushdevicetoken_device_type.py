# Generated manually for PushDeviceToken device_type + longer FCM token

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0041_refresh_all_iroute_email_templates'),
    ]

    operations = [
        migrations.AddField(
            model_name='pushdevicetoken',
            name='device_type',
            field=models.PositiveSmallIntegerField(
                blank=True,
                help_text='0=iOS, 1=Android; null if unknown/web',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='pushdevicetoken',
            name='device_token',
            field=models.CharField(max_length=2048, unique=True),
        ),
    ]
