from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0007_tenantuser_refno_sequence'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantRole',
            fields=[
                ('role_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('role_name_en', models.CharField(max_length=150, unique=True)),
                ('role_name_ar', models.CharField(max_length=150, unique=True)),
                ('description_en', models.CharField(blank=True, default='', max_length=255)),
                ('description_ar', models.CharField(blank=True, default='', max_length=255)),
                ('status', models.CharField(choices=[('Active', 'Active'), ('Inactive', 'Inactive'), ('Draft', 'Draft')], default='Active', max_length=12)),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_roles',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TenantRolePermission',
            fields=[
                ('permission_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('module_name', models.CharField(max_length=100)),
                ('form_name', models.CharField(max_length=120)),
                ('can_view', models.BooleanField(default=False)),
                ('can_create', models.BooleanField(default=False)),
                ('can_edit', models.BooleanField(default=False)),
                ('can_delete', models.BooleanField(default=False)),
                ('can_post', models.BooleanField(default=False)),
                ('can_approve', models.BooleanField(default=False)),
                ('can_export', models.BooleanField(default=False)),
                ('can_print', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permissions', to='tenant_workspace.tenantrole')),
            ],
            options={
                'db_table': 'tenant_role_permissions',
                'ordering': ['module_name', 'form_name'],
                'unique_together': {('role', 'module_name', 'form_name')},
            },
        ),
    ]
