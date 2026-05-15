# Remove denormalized *_ref / booking_no copies; use direct ForeignKeys.

from django.db import migrations, models
import django.db.models.deletion


def backfill_document_handover_foreign_keys(apps, schema_editor):
    TenantDocumentHandover = apps.get_model('tenant_workspace', 'TenantDocumentHandover')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantShipmentDocument = apps.get_model('tenant_workspace', 'TenantShipmentDocument')

    for handover in TenantDocumentHandover.objects.all().iterator():
        updates = {}
        shipment_no = (getattr(handover, 'shipment_ref', None) or '').strip()
        if shipment_no:
            shipment = TenantShipment.objects.filter(shipment_no=shipment_no).first()
            if shipment:
                updates['shipment_id'] = shipment.shipment_id
                if shipment.booking_id:
                    updates['booking_id'] = shipment.booking_id

        if not updates.get('booking_id'):
            booking_no = (getattr(handover, 'booking_no', None) or '').strip()
            if booking_no:
                booking = TenantBooking.objects.filter(booking_no=booking_no).first()
                if booking:
                    updates['booking_id'] = booking.booking_id

        document_ref = (getattr(handover, 'document_ref', None) or '').strip()
        if document_ref:
            document = TenantShipmentDocument.objects.filter(record_no=document_ref).first()
            if document:
                updates['document_id'] = document.document_id

        pod_record_ref = (getattr(handover, 'pod_record_ref', None) or '').strip()
        if pod_record_ref:
            pod_document = TenantShipmentDocument.objects.filter(record_no=pod_record_ref).first()
            if pod_document:
                updates['pod_document_id'] = pod_document.document_id

        if updates:
            TenantDocumentHandover.objects.filter(pk=handover.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0065_tenantshipmentsurcharge_foreign_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantdocumenthandover',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='document_handovers',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='tenantdocumenthandover',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='document_handovers',
                to='tenant_workspace.tenantshipment',
            ),
        ),
        migrations.AddField(
            model_name='tenantdocumenthandover',
            name='document',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='handovers',
                to='tenant_workspace.tenantshipmentdocument',
            ),
        ),
        migrations.AddField(
            model_name='tenantdocumenthandover',
            name='pod_document',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='pod_handovers',
                to='tenant_workspace.tenantshipmentdocument',
            ),
        ),
        migrations.RunPython(backfill_document_handover_foreign_keys, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name='tenantshipment',
            name='tenant_shipment_booking_idx',
        ),
        migrations.RemoveIndex(
            model_name='tenantshipmentdocument',
            name='tenant_shipdoc_shipref_idx',
        ),
        migrations.RemoveIndex(
            model_name='tenantdocumenthandover',
            name='tenant_doc_ho_ship_idx',
        ),
        migrations.RemoveField(model_name='tenantshipment', name='booking_no'),
        migrations.RemoveField(model_name='tenantshipment', name='client_account_ref'),
        migrations.RemoveField(model_name='tenantshipment', name='driver_ref'),
        migrations.RemoveField(model_name='tenantshipment', name='from_location'),
        migrations.RemoveField(model_name='tenantshipment', name='to_location'),
        migrations.RemoveField(model_name='tenantshipmentdocument', name='booking_no'),
        migrations.RemoveField(model_name='tenantshipmentdocument', name='booking_item'),
        migrations.RemoveField(model_name='tenantshipmentdocument', name='shipment_ref'),
        migrations.RemoveField(model_name='tenanttruckmovementlog', name='booking_ref'),
        migrations.RemoveField(model_name='tenanttruckmovementlog', name='shipment_ref'),
        migrations.RemoveField(model_name='tenanttruckmovementlog', name='truck_ref'),
        migrations.RemoveField(model_name='tenanttruckmovementlog', name='driver_ref'),
        migrations.RemoveField(model_name='tenanttruckmovementlog', name='from_location'),
        migrations.RemoveField(model_name='tenanttruckmovementlog', name='to_location'),
        migrations.RemoveField(model_name='tenantdocumenthandover', name='booking_no'),
        migrations.RemoveField(model_name='tenantdocumenthandover', name='booking_item'),
        migrations.RemoveField(model_name='tenantdocumenthandover', name='shipment_ref'),
        migrations.RemoveField(model_name='tenantdocumenthandover', name='document_ref'),
        migrations.RemoveField(model_name='tenantdocumenthandover', name='pod_record_ref'),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(fields=['booking', 'booking_item_ref'], name='tenant_shipment_booking_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantdocumenthandover',
            index=models.Index(fields=['shipment'], name='tenant_doc_ho_ship_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantdocumenthandover',
            index=models.Index(fields=['booking'], name='tenant_doc_ho_booking_idx'),
        ),
    ]
