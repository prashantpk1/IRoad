from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0014_tenantclientcontract'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantClientContractSetting',
            fields=[
                ('setting_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('expired_contract_handling_mode', models.CharField(choices=[('Auto-Deactivate', 'Auto-Deactivate'), ('Do Nothing', 'Do Nothing'), ('Deactivate After Grace', 'Deactivate After Grace')], default='Do Nothing', max_length=30)),
                ('grace_period_days', models.PositiveSmallIntegerField(default=30)),
                ('pre_expiry_notification_days', models.PositiveSmallIntegerField(default=30)),
                ('post_expiry_notification_days', models.PositiveSmallIntegerField(default=30)),
                ('notification_frequency', models.CharField(choices=[('Once', 'Once'), ('Daily', 'Daily'), ('Weekly', 'Weekly')], default='Daily', max_length=10)),
                ('notification_audience', models.CharField(choices=[('System Admin', 'System Admin'), ('Admin+Finance', 'Admin+Finance')], default='System Admin', max_length=20)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tenant_client_contract_settings',
            },
        ),
    ]
