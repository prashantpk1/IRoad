# Tenant in-app notifications (bell panel).

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0089_drivertreasurytransaction_fk_shipment_action_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantInAppNotification',
            fields=[
                ('notification_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('recipient_key', models.CharField(db_index=True, help_text="'owner' for tenant-owner session, else TenantUser UUID.", max_length=64)),
                ('category', models.CharField(choices=[('contract_pre_expiry', 'Contract Pre-Expiry'), ('contract_post_expiry', 'Contract Post-Expiry'), ('contract_grace', 'Contract Grace Period')], max_length=32)),
                ('title', models.CharField(max_length=255)),
                ('message', models.TextField()),
                ('href', models.CharField(blank=True, default='', max_length=500)),
                ('source_key', models.CharField(max_length=128)),
                ('is_read', models.BooleanField(db_index=True, default=False)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('contract', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='in_app_notifications', to='tenant_workspace.tenantclientcontract')),
                ('recipient_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='in_app_notifications', to='tenant_workspace.tenantuser')),
            ],
            options={
                'db_table': 'tenant_in_app_notifications',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='tenantinappnotification',
            index=models.Index(fields=['recipient_key', 'is_read'], name='tenant_notif_rcpt_read_idx'),
        ),
        migrations.AddConstraint(
            model_name='tenantinappnotification',
            constraint=models.UniqueConstraint(fields=('recipient_key', 'source_key'), name='tenant_notif_rcpt_source_uniq'),
        ),
    ]
