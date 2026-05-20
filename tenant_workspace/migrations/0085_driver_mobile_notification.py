# Driver mobile inbox for dashboard notification summary + FCM ingest.

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0084_current_job_action_log_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='DriverMobileNotification',
            fields=[
                (
                    'notification_id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('category', models.CharField(
                    choices=[
                        ('general', 'General'),
                        ('critical', 'Critical'),
                        ('assignment', 'Assignment'),
                        ('operational_warning', 'Operational Warning'),
                    ],
                    default='general',
                    max_length=32,
                )),
                ('severity', models.CharField(
                    choices=[
                        ('info', 'Info'),
                        ('warning', 'Warning'),
                        ('critical', 'Critical'),
                    ],
                    default='info',
                    max_length=16,
                )),
                ('source', models.CharField(
                    choices=[
                        ('system', 'System'),
                        ('operational', 'Operational'),
                        ('push', 'Push'),
                        ('fcm', 'FCM'),
                    ],
                    default='system',
                    max_length=16,
                )),
                ('title', models.CharField(max_length=255)),
                ('body', models.TextField(blank=True, default='')),
                ('event_code', models.CharField(blank=True, default='', max_length=64)),
                ('is_read', models.BooleanField(db_index=True, default=False)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('shipment_id', models.UUIDField(blank=True, null=True)),
                ('movement_id', models.UUIDField(blank=True, null=True)),
                ('fcm_message_id', models.CharField(blank=True, default='', max_length=128)),
                ('push_receipt_id', models.UUIDField(blank=True, null=True)),
                ('dedupe_key', models.CharField(
                    blank=True,
                    db_index=True,
                    default='',
                    max_length=128,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                (
                    'driver',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='mobile_notifications',
                        to='tenant_workspace.drivermaster',
                    ),
                ),
            ],
            options={
                'db_table': 'tenant_driver_mobile_notifications',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='drivermobilenotification',
            index=models.Index(
                fields=['driver', 'is_read', '-created_at'],
                name='tenant_drv_notif_unread_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='drivermobilenotification',
            index=models.Index(
                fields=['driver', 'category', 'is_read'],
                name='tenant_drv_notif_cat_idx',
            ),
        ),
        migrations.AddConstraint(
            model_name='drivermobilenotification',
            constraint=models.UniqueConstraint(
                condition=~models.Q(dedupe_key=''),
                fields=('driver', 'dedupe_key'),
                name='tenant_drv_notif_dedupe_uniq',
            ),
        ),
    ]
