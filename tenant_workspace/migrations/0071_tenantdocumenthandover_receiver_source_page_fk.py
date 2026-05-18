# Document handover: receiver_user FK; handover line source_page FK to delivery-note page.

import uuid

from django.db import migrations, models
import django.db.models.deletion


def backfill_handover_line_source_page(apps, schema_editor):
    TenantDocumentHandoverLine = apps.get_model('tenant_workspace', 'TenantDocumentHandoverLine')
    TenantShipmentPodPage = apps.get_model('tenant_workspace', 'TenantShipmentPodPage')
    for line in TenantDocumentHandoverLine.objects.exclude(doc_page='').iterator():
        raw = (line.doc_page or '').strip()
        if not raw:
            continue
        try:
            page_uuid = uuid.UUID(raw)
        except ValueError:
            continue
        if TenantShipmentPodPage.objects.filter(pk=page_uuid).exists():
            TenantDocumentHandoverLine.objects.filter(pk=line.pk).update(source_page_id=page_uuid)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0070_alter_tenantshipmentdocument_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantdocumenthandover',
            name='receiver_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='document_handovers_received',
                to='tenant_workspace.tenantuser',
            ),
        ),
        migrations.AddField(
            model_name='tenantdocumenthandoverline',
            name='source_page',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='handover_lines',
                to='tenant_workspace.tenantshipmentpodpage',
            ),
        ),
        migrations.RunPython(backfill_handover_line_source_page, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenantdocumenthandoverline',
            index=models.Index(fields=['source_page'], name='tenant_doc_ho_srcpage_idx'),
        ),
    ]
