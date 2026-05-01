from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0011_tenantclientaccountsetting'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantClientAttachment',
            fields=[
                ('attachment_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('attachment_no', models.CharField(max_length=64, unique=True)),
                ('attachment_sequence', models.PositiveIntegerField(default=0)),
                ('attachment_date', models.DateField(default=django.utils.timezone.localdate)),
                ('is_expiry_applicable', models.BooleanField(default=False)),
                ('expiry_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(choices=[('Valid', 'Valid'), ('Expired', 'Expired'), ('Does Not Expire', 'Does Not Expire')], default='Does Not Expire', max_length=20)),
                ('attachment_file', models.FileField(upload_to='tenant/client_attachments/')),
                ('file_notes', models.TextField(blank=True, default='')),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client_account', models.ForeignKey(db_column='client_id', on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='tenant_workspace.tenantclientaccount')),
            ],
            options={
                'db_table': 'tenant_client_attachments',
                'ordering': ['-created_at'],
            },
        ),
    ]
