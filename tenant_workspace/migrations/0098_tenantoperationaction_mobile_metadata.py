from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0097_merge_20260527_0930'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantoperationaction',
            name='admin_only',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenantoperationaction',
            name='auto_treasury_post',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenantoperationaction',
            name='condition_code',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='tenantoperationaction',
            name='mobile_visible',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tenantoperationaction',
            name='prerequisite_action_codes',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddIndex(
            model_name='tenantoperationaction',
            index=models.Index(
                fields=['status', 'mobile_visible'],
                name='tenant_op_act_mobile_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantoperationaction',
            index=models.Index(
                fields=['status', 'admin_only'],
                name='tenant_op_act_admin_idx',
            ),
        ),
    ]
