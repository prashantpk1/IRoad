# CG-001 Cargo Master + category (tenant schema).

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0017_ensure_tenant_client_attachments_table'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantCargoCategory',
            fields=[
                ('category_id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ('category_code', models.CharField(max_length=64, unique=True)),
                ('category_sequence', models.PositiveIntegerField(default=0)),
                ('name_english', models.CharField(max_length=200)),
                ('name_arabic', models.CharField(blank=True, default='', max_length=200)),
                (
                    'status',
                    models.CharField(
                        max_length=12,
                        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
                        default='Active',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_cargo_category',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TenantCargoMaster',
            fields=[
                ('cargo_id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ('cargo_code', models.CharField(max_length=64, unique=True)),
                ('cargo_sequence', models.PositiveIntegerField(default=0)),
                ('display_name', models.CharField(max_length=200)),
                ('arabic_label', models.CharField(blank=True, default='', max_length=200)),
                ('english_label', models.CharField(blank=True, default='', max_length=200)),
                ('client_sku_external_ref', models.CharField(blank=True, default='', max_length=120)),
                ('uom', models.CharField(blank=True, default='', max_length=64)),
                ('weight_per_unit', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ('volume_per_unit', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ('length', models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True)),
                ('width', models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True)),
                ('height', models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True)),
                ('refrigerated_goods', models.BooleanField(default=False)),
                ('min_temp', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('max_temp', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('dangerous_goods', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True, default='')),
                (
                    'status',
                    models.CharField(
                        max_length=12,
                        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
                        default='Active',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'cargo_category',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='cargo_items',
                        to='tenant_workspace.tenantcargocategory',
                    ),
                ),
                (
                    'client_account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='cargo_items',
                        to='tenant_workspace.tenantclientaccount',
                    ),
                ),
            ],
            options={
                'db_table': 'tenant_cargo_master',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TenantCargoMasterAttachment',
            fields=[
                ('attachment_id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ('file', models.FileField(upload_to='tenant/cargo_master_attachments/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'cargo_master',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='attachments',
                        to='tenant_workspace.tenantcargomaster',
                    ),
                ),
            ],
            options={
                'db_table': 'tenant_cargo_master_attachment',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='tenantcargomaster',
            index=models.Index(fields=['client_account', 'status'], name='tenant_cargo_client_status_idx'),
        ),
    ]
