from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0108_tenantrolepermission_matrix_sidebar_flags'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tenantclientcontract',
            name='client_account',
            field=models.ForeignKey(
                db_column='client_id',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='contracts',
                to='tenant_workspace.tenantclientaccount',
            ),
        ),
        migrations.AddIndex(
            model_name='tenantclientcontract',
            index=models.Index(
                fields=['client_account', 'start_date', 'end_date'],
                name='tnt_client_contract_period_idx',
            ),
        ),
    ]
