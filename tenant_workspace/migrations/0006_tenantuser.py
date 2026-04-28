from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0005_organizationprofile_extra_profile_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantUser',
            fields=[
                ('user_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('username', models.CharField(max_length=150, unique=True)),
                ('full_name', models.CharField(max_length=200)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('mobile_country_code', models.CharField(blank=True, default='', max_length=8)),
                ('mobile_no', models.CharField(blank=True, default='', max_length=30)),
                ('password_hash', models.CharField(max_length=255)),
                ('role_name', models.CharField(default='Administrator', max_length=100)),
                ('status', models.CharField(choices=[('Active', 'Active'), ('Inactive', 'Inactive')], default='Active', max_length=12)),
                ('last_login_at', models.DateTimeField(blank=True, null=True)),
                ('login_attempts', models.PositiveIntegerField(default=0)),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_users',
                'ordering': ['-created_at'],
            },
        ),
    ]
