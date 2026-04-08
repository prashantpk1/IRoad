from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0018_tenant_portal_bootstrap_password'),
    ]

    operations = [
        migrations.CreateModel(
            name='PushDeviceToken',
            fields=[
                ('token_id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('user_domain', models.CharField(choices=[('Tenant_User', 'Tenant User'), ('Driver', 'Driver'), ('Admin', 'Admin')], max_length=20)),
                ('reference_id', models.CharField(help_text='Domain entity ID, e.g. tenant user ID or driver ID', max_length=100)),
                ('device_token', models.CharField(max_length=512, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'comm_push_device_tokens',
                'ordering': ['-updated_at'],
            },
        ),
    ]
