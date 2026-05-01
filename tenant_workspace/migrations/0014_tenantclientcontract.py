from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0013_tenantclientcontact'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantClientContract',
            fields=[
                ('contract_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('contract_no', models.CharField(max_length=64, unique=True)),
                ('contract_sequence', models.PositiveIntegerField(default=0)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('status', models.CharField(choices=[('Upcoming', 'Upcoming'), ('Active', 'Active'), ('Expired', 'Expired')], default='Upcoming', max_length=20)),
                ('notes', models.TextField(blank=True, default='')),
                ('contract_attachment', models.FileField(upload_to='tenant/client_contracts/')),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client_account', models.OneToOneField(db_column='client_id', on_delete=django.db.models.deletion.CASCADE, related_name='contract', to='tenant_workspace.tenantclientaccount')),
            ],
            options={
                'db_table': 'tenant_client_contracts',
                'ordering': ['-created_at'],
            },
        ),
    ]
