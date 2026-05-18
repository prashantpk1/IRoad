# OP-DOC: TenantShipmentDocumentPage entity; spec pod_status Pending / Hard Copy Received.

from django.db import migrations, models
import django.db.models.deletion
import uuid


def backfill_document_pages_from_pod_pages(apps, schema_editor):
    TenantShipmentDocument = apps.get_model('tenant_workspace', 'TenantShipmentDocument')
    TenantShipmentDocumentPage = apps.get_model('tenant_workspace', 'TenantShipmentDocumentPage')
    TenantShipmentPodPage = apps.get_model('tenant_workspace', 'TenantShipmentPodPage')

    for document in TenantShipmentDocument.objects.all().iterator():
        if TenantShipmentDocumentPage.objects.filter(document_id=document.pk).exists():
            continue
        for pod_line in TenantShipmentPodPage.objects.filter(document_id=document.pk).order_by('line_no'):
            page_no = 1
            raw_page = (pod_line.doc_page or '').strip()
            if raw_page.isdigit():
                page_no = int(raw_page)
            elif raw_page.lower().startswith('page-'):
                try:
                    page_no = int(raw_page.split('-', 1)[1])
                except (IndexError, ValueError):
                    page_no = pod_line.line_no or 1
            else:
                page_no = pod_line.line_no or 1
            TenantShipmentDocumentPage.objects.create(
                document_id=document.pk,
                line_no=pod_line.line_no or 1,
                doc_ref_no=(pod_line.source or document.document_ref_no or '')[:120],
                extra_ref=pod_line.action_log or '',
                physical_page_no=max(page_no, 1),
                completion_status=pod_line.soft_copy_status or '',
                signer_location=pod_line.physical_location or '',
                attachment_storage_path=(pod_line.map_url or '')[:500],
                attachment_label=pod_line.attachment_label or '',
            )


def migrate_pod_status_values(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantShipment.objects.filter(pod_status='Compliant').update(pod_status='Hard Copy Received')
    TenantShipment.objects.filter(pod_status='Not Compliant').update(pod_status='Pending')


def reverse_pod_status_values(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantShipment.objects.filter(pod_status='Hard Copy Received').update(pod_status='Compliant')
    TenantShipment.objects.filter(pod_status='Pending').update(pod_status='Not Compliant')


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0071_tenantdocumenthandover_receiver_source_page_fk'),
    ]

    operations = [
        migrations.CreateModel(
            name='TenantShipmentDocumentPage',
            fields=[
                ('page_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('line_no', models.PositiveIntegerField(default=1)),
                ('doc_ref_no', models.CharField(blank=True, default='', max_length=120)),
                ('extra_ref', models.CharField(blank=True, default='', max_length=120)),
                ('physical_page_no', models.PositiveIntegerField(default=1)),
                ('completion_status', models.CharField(blank=True, choices=[('Completed', 'Completed'), ('Not Completed', 'Not Completed')], default='', max_length=20)),
                ('signer_location', models.CharField(blank=True, choices=[('With Driver', 'With Driver'), ('In Company', 'In Company'), ('With Client', 'With Client')], default='', max_length=120)),
                ('attachment_storage_path', models.CharField(blank=True, default='', max_length=500)),
                ('attachment_label', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='document_pages', to='tenant_workspace.tenantshipmentdocument')),
            ],
            options={
                'db_table': 'tenant_shipment_document_pages',
                'ordering': ['line_no', 'created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='tenantshipmentdocumentpage',
            index=models.Index(fields=['document', 'line_no'], name='tenant_shipdocpage_doc_ln_idx'),
        ),
        migrations.RunPython(backfill_document_pages_from_pod_pages, migrations.RunPython.noop),
        migrations.RunPython(migrate_pod_status_values, reverse_pod_status_values),
        migrations.AlterField(
            model_name='tenantshipment',
            name='pod_status',
            field=models.CharField(
                choices=[
                    ('Pending', 'Pending'),
                    ('Hard Copy Received', 'Hard Copy Received'),
                    ('Compliant', 'Compliant'),
                    ('Not Compliant', 'Not Compliant'),
                ],
                default='Pending',
                max_length=20,
            ),
        ),
    ]
