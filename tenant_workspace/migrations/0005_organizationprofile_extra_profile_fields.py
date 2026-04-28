from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0004_autonumbersequence_organizationprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizationprofile',
            name='secondary_currency_code',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
        migrations.AddField(
            model_name='organizationprofile',
            name='support_email',
            field=models.EmailField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='organizationprofile',
            name='support_mobile_1',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='organizationprofile',
            name='support_mobile_2',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='organizationprofile',
            name='driver_instructions',
            field=models.TextField(blank=True, default=''),
        ),
    ]

