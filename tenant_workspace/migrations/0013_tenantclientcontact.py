from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0012_tenantclientattachment'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantClientContact',
            fields=[
                ('contact_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200)),
                ('email', models.EmailField(blank=True, default='', max_length=150)),
                ('mobile_number', models.CharField(blank=True, default='', max_length=30)),
                ('telephone_number', models.CharField(blank=True, default='', max_length=30)),
                ('extension', models.CharField(blank=True, default='', max_length=30)),
                ('position', models.CharField(blank=True, default='', max_length=120)),
                ('is_primary', models.BooleanField(default=False)),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client_account', models.ForeignKey(db_column='client_id', on_delete=django.db.models.deletion.CASCADE, related_name='contacts', to='tenant_workspace.tenantclientaccount')),
            ],
            options={
                'db_table': 'tenant_client_contacts',
                'ordering': ['-created_at'],
            },
        ),
    ]
