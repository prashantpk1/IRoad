from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0009_tenantuser_temp_password_expires_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantClientAccount',
            fields=[
                ('account_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('account_no', models.CharField(max_length=64, unique=True)),
                ('account_sequence', models.PositiveIntegerField(default=0)),
                ('client_type', models.CharField(choices=[('Individual', 'Individual'), ('Business', 'Business')], default='Individual', max_length=20)),
                ('status', models.CharField(choices=[('Active', 'Active'), ('Inactive', 'Inactive')], default='Active', max_length=12)),
                ('name_arabic', models.CharField(blank=True, default='', max_length=200)),
                ('name_english', models.CharField(max_length=200)),
                ('display_name', models.CharField(max_length=200)),
                ('preferred_currency', models.CharField(blank=True, default='', max_length=10)),
                ('billing_street_1', models.CharField(max_length=255)),
                ('billing_street_2', models.CharField(blank=True, default='', max_length=255)),
                ('billing_city', models.CharField(max_length=100)),
                ('billing_region', models.CharField(blank=True, default='', max_length=100)),
                ('postal_code', models.CharField(blank=True, default='', max_length=30)),
                ('country', models.CharField(max_length=10)),
                ('credit_limit_amount', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('limit_currency_code', models.CharField(blank=True, default='SAR', max_length=10)),
                ('payment_term_days', models.PositiveIntegerField(default=0)),
                ('commercial_registration_no', models.CharField(blank=True, default='', max_length=80)),
                ('tax_registration_no', models.CharField(blank=True, default='', max_length=80)),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_client_accounts',
                'ordering': ['-created_at'],
            },
        ),
    ]
