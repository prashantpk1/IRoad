# Generated manually for TenantShipmentDocument FK linkage.

from django.db import migrations, models
import django.db.models.deletion


def backfill_shipment_document_foreign_keys(apps, schema_editor):
    TenantShipmentDocument = apps.get_model('tenant_workspace', 'TenantShipmentDocument')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')

    for document in TenantShipmentDocument.objects.all().iterator():
        updates = {}
        shipment_ref = (document.shipment_ref or '').strip()
        if shipment_ref:
            shipment = TenantShipment.objects.filter(shipment_no=shipment_ref).first()
            if shipment:
                updates['shipment_id'] = shipment.shipment_id
                if shipment.booking_id:
                    updates['booking_id'] = shipment.booking_id

        if not updates.get('booking_id'):
            booking_no = (document.booking_no or '').strip()
            if booking_no:
                booking = TenantBooking.objects.filter(booking_no=booking_no).first()
                if booking:
                    updates['booking_id'] = booking.booking_id

        if updates:
            TenantShipmentDocument.objects.filter(pk=document.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0063_tenantshipment_address_cargo_foreign_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipmentdocument',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipment_documents',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipmentdocument',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='documents',
                to='tenant_workspace.tenantshipment',
            ),
        ),
        migrations.RunPython(backfill_shipment_document_foreign_keys, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenantshipmentdocument',
            index=models.Index(fields=['booking'], name='tenant_shipdoc_booking_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentdocument',
            index=models.Index(fields=['shipment'], name='tenant_shipdoc_shipment_idx'),
        ),
    ]
