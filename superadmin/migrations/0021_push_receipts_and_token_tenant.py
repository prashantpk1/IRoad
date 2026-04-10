from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0020_comm_log_retention_periodic_task'),
    ]

    operations = [
        migrations.AddField(
            model_name='pushdevicetoken',
            name='tenant',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='push_device_tokens',
                to='superadmin.tenantprofile',
            ),
        ),
        migrations.CreateModel(
            name='PushNotificationReceipt',
            fields=[
                ('receipt_id', models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ('device_token', models.CharField(max_length=512)),
                ('user_domain', models.CharField(choices=[('Tenant_User', 'Tenant User'), ('Driver', 'Driver'), ('Admin', 'Admin')], max_length=20)),
                ('reference_id', models.CharField(max_length=100)),
                ('title', models.CharField(max_length=255)),
                ('message', models.TextField()),
                ('action_link', models.URLField(blank=True, null=True)),
                ('event_code', models.CharField(blank=True, max_length=50, null=True)),
                ('delivery_status', models.CharField(choices=[('Sent', 'Sent'), ('Failed', 'Failed')], default='Sent', max_length=20)),
                ('error_details', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('notification', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='receipts', to='superadmin.pushnotification')),
                ('tenant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='push_receipts', to='superadmin.tenantprofile')),
            ],
            options={
                'db_table': 'comm_push_receipts',
                'ordering': ['-created_at'],
            },
        ),
    ]

