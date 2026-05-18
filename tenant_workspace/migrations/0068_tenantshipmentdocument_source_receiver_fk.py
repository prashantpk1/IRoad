# POD transaction: source delivery-note document FK + receiver user FK.

from django.db import migrations, models
import django.db.models.deletion


def backfill_source_document_from_ref(apps, schema_editor):
    TenantShipmentDocument = apps.get_model('tenant_workspace', 'TenantShipmentDocument')
    for document in TenantShipmentDocument.objects.exclude(document_ref_no='').iterator():
        ref = (document.document_ref_no or '').strip()
        if not ref or not document.shipment_id:
            continue
        source = (
            TenantShipmentDocument.objects.filter(
                shipment_id=document.shipment_id,
                document_ref_no=ref,
                is_delivery_note=True,
            )
            .exclude(pk=document.pk)
            .order_by('-created_at')
            .first()
        )
        if source:
            TenantShipmentDocument.objects.filter(pk=document.pk).update(source_document_id=source.pk)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0067_alter_tenantshipmentdocument_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipmentdocument',
            name='source_document',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='pod_source_children',
                to='tenant_workspace.tenantshipmentdocument',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipmentdocument',
            name='receiver_user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='received_shipment_documents',
                to='tenant_workspace.tenantuser',
            ),
        ),
        migrations.RunPython(backfill_source_document_from_ref, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenantshipmentdocument',
            index=models.Index(fields=['source_document'], name='tenant_shipdoc_source_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentdocument',
            index=models.Index(fields=['receiver_user'], name='tenant_shipdoc_receiver_idx'),
        ),
    ]
