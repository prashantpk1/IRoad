from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0006_tenantuser'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantuser',
            name='account_sequence',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='tenantuser',
            name='tenant_ref_no',
            field=models.CharField(blank=True, default='', max_length=64, unique=True),
        ),
    ]
