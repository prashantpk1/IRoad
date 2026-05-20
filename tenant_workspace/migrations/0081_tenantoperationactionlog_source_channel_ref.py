from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0080_tenantoperationactionlog_idempotency_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantoperationactionlog',
            name='source_channel',
            field=models.CharField(blank=True, default='admin_manual', max_length=32),
        ),
        migrations.AddField(
            model_name='tenantoperationactionlog',
            name='source_ref',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['source_channel'], name='tenant_oal_channel_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['source_ref'], name='tenant_oal_source_ref_idx'),
        ),
    ]

