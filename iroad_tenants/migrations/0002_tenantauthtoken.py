import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0023_soft_delete_flags'),
        ('iroad_tenants', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantAuthToken',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('token', models.CharField(max_length=100, unique=True)),
                ('token_type', models.CharField(choices=[('invite', 'invite')], default='invite', max_length=20)),
                ('is_used', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('tenant_profile', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='tenant_auth_tokens', to='superadmin.tenantprofile')),
            ],
            options={
                'db_table': 'iroad_tenants_auth_tokens',
            },
        ),
    ]
