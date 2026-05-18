# POD line rows: source_page FK to delivery-note page (replaces UUID in doc_page char).

import uuid

from django.db import migrations, models
import django.db.models.deletion


def backfill_pod_line_source_page(apps, schema_editor):
    TenantShipmentPodPage = apps.get_model('tenant_workspace', 'TenantShipmentPodPage')
    for line in TenantShipmentPodPage.objects.exclude(doc_page='').iterator():
        raw = (line.doc_page or '').strip()
        if not raw:
            continue
        try:
            page_uuid = uuid.UUID(raw)
        except ValueError:
            continue
        if TenantShipmentPodPage.objects.filter(pk=page_uuid).exists():
            TenantShipmentPodPage.objects.filter(pk=line.pk).update(source_page_id=page_uuid)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0068_tenantshipmentdocument_source_receiver_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipmentpodpage',
            name='source_page',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='pod_lines_referencing',
                to='tenant_workspace.tenantshipmentpodpage',
            ),
        ),
        migrations.RunPython(backfill_pod_line_source_page, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenantshipmentpodpage',
            index=models.Index(fields=['source_page'], name='tenant_podpage_source_idx'),
        ),
    ]
