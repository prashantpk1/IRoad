# Generated manually for CP-PCS-P1 hardening

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('superadmin', '0013_tenantprofile_scheduled_downgrade'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantprofile',
            name='api_bridge_secret_hash',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Hashed API key for /api/v1/* tenant bridge (set from Control Panel).',
            ),
        ),
        migrations.AddField(
            model_name='activesession',
            name='redis_jti',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                max_length=128,
                help_text='Redis session token id for real-time revocation (mirrors admin JTI).',
            ),
        ),
        migrations.AddField(
            model_name='activesession',
            name='tenant',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='active_sessions',
                to='superadmin.tenantprofile',
            ),
        ),
    ]
