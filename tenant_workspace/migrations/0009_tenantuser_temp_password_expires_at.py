from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0008_tenantrole_and_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantuser',
            name='temp_password_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
