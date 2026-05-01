from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0010_tenantclientaccount'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantclientaccount',
            name='national_id',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.CreateModel(
            name='TenantClientAccountSetting',
            fields=[
                ('setting_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('require_national_id_individual', models.BooleanField(default=True)),
                ('require_commercial_registration_business', models.BooleanField(default=False)),
                ('require_tax_vat_registration_business', models.BooleanField(default=False)),
                ('default_client_status', models.CharField(choices=[('Active', 'Active'), ('Inactive', 'Inactive')], default='Active', max_length=12)),
                ('default_client_type', models.CharField(choices=[('Individual', 'Individual'), ('Business', 'Business')], default='Individual', max_length=20)),
                ('default_preferred_currency', models.CharField(blank=True, default='', max_length=10)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_client_account_settings',
            },
        ),
    ]
