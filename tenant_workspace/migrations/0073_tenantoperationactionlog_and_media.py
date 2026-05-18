import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0072_shipment_document_page_and_pod_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantOperationActionLog',
            fields=[
                ('log_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('log_no', models.CharField(max_length=64, unique=True)),
                ('log_sequence', models.PositiveIntegerField(default=0)),
                ('log_date', models.DateTimeField()),
                ('source', models.CharField(blank=True, default='Manual', max_length=32)),
                ('created_by_label', models.CharField(blank=True, default='', max_length=200)),
                ('notes', models.TextField(blank=True, default='')),
                ('latitude', models.CharField(blank=True, default='', max_length=32)),
                ('longitude', models.CharField(blank=True, default='', max_length=32)),
                ('map_link', models.URLField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('booking', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='operation_action_logs', to='tenant_workspace.tenantbooking')),
                ('driver', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='operation_action_logs', to='tenant_workspace.drivermaster')),
                ('operation_action', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='action_logs', to='tenant_workspace.tenantoperationaction')),
                ('shipment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='operation_action_logs', to='tenant_workspace.tenantshipment')),
                ('truck', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='operation_action_logs', to='tenant_workspace.truckmaster')),
                ('truck_movement', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='operation_action_logs', to='tenant_workspace.tenanttruckmovementlog')),
            ],
            options={
                'db_table': 'tenant_operation_action_logs',
                'ordering': ['-log_date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='TenantOperationActionMedia',
            fields=[
                ('media_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('line_no', models.PositiveIntegerField(default=1)),
                ('media_type', models.CharField(blank=True, default='', max_length=16)),
                ('captured_at', models.DateTimeField(blank=True, null=True)),
                ('description', models.CharField(blank=True, default='', max_length=255)),
                ('file', models.FileField(blank=True, default='', upload_to='tenant_operation_action_media/%Y/%m/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('action_log', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='media_rows', to='tenant_workspace.tenantoperationactionlog')),
            ],
            options={
                'db_table': 'tenant_operation_action_media',
                'ordering': ['line_no', 'created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['log_no'], name='tenant_oal_no_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['log_date'], name='tenant_oal_date_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['source'], name='tenant_oal_source_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['booking'], name='tenant_oal_booking_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['shipment'], name='tenant_oal_shipment_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionlog',
            index=models.Index(fields=['truck_movement'], name='tenant_oal_movement_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantoperationactionmedia',
            index=models.Index(fields=['action_log'], name='tenant_oal_media_log_idx'),
        ),
    ]
