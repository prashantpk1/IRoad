from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0111_operation_pod_type_status_values'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='from_location_address',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='to_location_address',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='from_latitude',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='from_longitude',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='to_latitude',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='to_longitude',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
