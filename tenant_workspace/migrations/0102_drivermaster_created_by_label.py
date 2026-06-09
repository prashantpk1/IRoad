from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0101_truckattachment_stats'),
    ]

    operations = [
        migrations.AddField(
            model_name='drivermaster',
            name='created_by_label',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
