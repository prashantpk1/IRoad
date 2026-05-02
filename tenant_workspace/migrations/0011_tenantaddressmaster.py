# Generated manually for AD-001 Address Master (tenant schema).

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0010_tenantclientaccount'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantAddressMaster',
            fields=[
                ('address_id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ('address_code', models.CharField(max_length=64, unique=True)),
                ('address_sequence', models.PositiveIntegerField(default=0)),
                ('display_name', models.CharField(max_length=200)),
                ('arabic_label', models.CharField(blank=True, default='', max_length=200)),
                ('english_label', models.CharField(blank=True, default='', max_length=200)),
                (
                    'address_category',
                    models.CharField(
                        max_length=32,
                        choices=[
                            ('Pickup Address', 'Pickup Address'),
                            ('Delivery Address', 'Delivery Address'),
                            ('Both', 'Both'),
                        ],
                    ),
                ),
                ('default_pickup_address', models.BooleanField(default=False)),
                ('default_delivery_address', models.BooleanField(default=False)),
                (
                    'status',
                    models.CharField(
                        max_length=12,
                        choices=[('Active', 'Active'), ('Inactive', 'Inactive')],
                        default='Active',
                    ),
                ),
                ('country_code', models.CharField(max_length=10)),
                ('province', models.CharField(max_length=120)),
                ('city', models.CharField(max_length=120)),
                ('district', models.CharField(blank=True, default='', max_length=120)),
                ('street', models.CharField(blank=True, default='', max_length=200)),
                ('building_no', models.CharField(blank=True, default='', max_length=50)),
                ('postal_code', models.CharField(blank=True, default='', max_length=30)),
                ('address_line_1', models.CharField(max_length=255)),
                ('address_line_2', models.CharField(blank=True, default='', max_length=255)),
                ('map_link', models.CharField(blank=True, default='', max_length=512)),
                ('site_instructions', models.TextField(blank=True, default='')),
                ('contact_name', models.CharField(blank=True, default='', max_length=200)),
                ('position', models.CharField(blank=True, default='', max_length=120)),
                ('mobile_no_1', models.CharField(max_length=30)),
                ('mobile_no_2', models.CharField(blank=True, default='', max_length=30)),
                ('whatsapp_no', models.CharField(blank=True, default='', max_length=30)),
                ('phone_no', models.CharField(blank=True, default='', max_length=30)),
                ('extension', models.CharField(blank=True, default='', max_length=20)),
                ('email', models.EmailField(blank=True, default='', max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'client_account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='addresses',
                        to='tenant_workspace.tenantclientaccount',
                    ),
                ),
            ],
            options={
                'db_table': 'tenant_address_master',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='tenantaddressmaster',
            index=models.Index(fields=['client_account', 'status'], name='tenant_addr_client_status_idx'),
        ),
    ]
