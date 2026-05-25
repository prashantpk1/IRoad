import uuid

from django.db import migrations, models
import django.db.models.deletion


def _coerce_uuid(value):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def forwards_copy_ref_to_fk(apps, schema_editor):
    BookingLine = apps.get_model('tenant_workspace', 'SalesInvoiceReportBooking')
    ShipmentLine = apps.get_model('tenant_workspace', 'SalesInvoiceReportShipment')
    SurchargeLine = apps.get_model('tenant_workspace', 'SalesInvoiceReportSurcharge')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantShipmentSurcharge = apps.get_model('tenant_workspace', 'TenantShipmentSurcharge')

    booking_by_id = {row.booking_id: row.pk for row in TenantBooking.objects.all()}
    booking_by_no = {row.booking_no: row.pk for row in TenantBooking.objects.all()}
    shipment_by_id = {row.shipment_id: row.pk for row in TenantShipment.objects.all()}
    shipment_by_no = {row.shipment_no: row.pk for row in TenantShipment.objects.all()}
    surcharge_by_id = {row.surcharge_id: row.pk for row in TenantShipmentSurcharge.objects.all()}

    for line in BookingLine.objects.all().iterator():
        booking_pk = booking_by_id.get(_coerce_uuid(getattr(line, 'booking_ref', None)))
        if booking_pk:
            line.booking_id = booking_pk
            line.save(update_fields=['booking_id'])

    for line in ShipmentLine.objects.all().iterator():
        shipment_pk = shipment_by_id.get(_coerce_uuid(getattr(line, 'shipment_ref', None)))
        booking_pk = None
        booking_ref = (getattr(line, 'booking_ref', '') or '').strip()
        if booking_ref:
            booking_pk = booking_by_id.get(_coerce_uuid(booking_ref)) or booking_by_no.get(booking_ref)
        if shipment_pk:
            line.shipment_id = shipment_pk
            if not booking_pk:
                shipment = TenantShipment.objects.filter(pk=shipment_pk).first()
                if shipment and shipment.booking_id:
                    booking_pk = shipment.booking_id
        if booking_pk:
            line.booking_id = booking_pk
        if shipment_pk or booking_pk:
            line.save(update_fields=['shipment_id', 'booking_id'])

    for line in SurchargeLine.objects.all().iterator():
        surcharge_pk = surcharge_by_id.get(_coerce_uuid(getattr(line, 'surcharge_trx_ref', None)))
        booking_pk = booking_by_id.get(_coerce_uuid(getattr(line, 'booking_ref', None)))
        shipment_pk = None
        shipment_ref = (getattr(line, 'shipment_ref', '') or '').strip()
        if shipment_ref:
            shipment_pk = shipment_by_id.get(_coerce_uuid(shipment_ref)) or shipment_by_no.get(shipment_ref)
        if surcharge_pk:
            line.surcharge_id = surcharge_pk
            surcharge = TenantShipmentSurcharge.objects.filter(pk=surcharge_pk).first()
            if surcharge:
                if not booking_pk and surcharge.booking_id:
                    booking_pk = surcharge.booking_id
                if not shipment_pk and surcharge.shipment_id:
                    shipment_pk = surcharge.shipment_id
        if booking_pk:
            line.booking_id = booking_pk
        if shipment_pk:
            line.shipment_id = shipment_pk
        if surcharge_pk or booking_pk or shipment_pk:
            line.save(update_fields=['surcharge_id', 'booking_id', 'shipment_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0084_merge_20260520_1216'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesinvoicereportbooking',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_invoice_report_lines',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='salesinvoicereportshipment',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_invoice_report_shipment_lines',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='salesinvoicereportshipment',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_invoice_report_lines',
                to='tenant_workspace.tenantshipment',
            ),
        ),
        migrations.AddField(
            model_name='salesinvoicereportshipment',
            name='pod_status',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='salesinvoicereportsurcharge',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_invoice_report_surcharge_lines',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='salesinvoicereportsurcharge',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_invoice_report_surcharge_lines',
                to='tenant_workspace.tenantshipment',
            ),
        ),
        migrations.AddField(
            model_name='salesinvoicereportsurcharge',
            name='surcharge',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sales_invoice_report_lines',
                to='tenant_workspace.tenantshipmentsurcharge',
            ),
        ),
        migrations.RunPython(forwards_copy_ref_to_fk, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='salesinvoicereportbooking',
            name='sir_unique_booking_per_report_uq',
        ),
        migrations.RemoveIndex(
            model_name='salesinvoicereportbooking',
            name='sir_booking_ref_idx',
        ),
        migrations.RemoveField(
            model_name='salesinvoicereportbooking',
            name='booking_ref',
        ),
        migrations.AddConstraint(
            model_name='salesinvoicereportbooking',
            constraint=models.UniqueConstraint(
                condition=models.Q(('booking__isnull', False)),
                fields=('report', 'booking'),
                name='sir_unique_booking_per_report_uq',
            ),
        ),
        migrations.AddIndex(
            model_name='salesinvoicereportbooking',
            index=models.Index(fields=['booking'], name='sir_booking_fk_idx'),
        ),
        migrations.RemoveIndex(
            model_name='salesinvoicereportshipment',
            name='sir_shipment_ref_idx',
        ),
        migrations.RemoveField(
            model_name='salesinvoicereportshipment',
            name='booking_ref',
        ),
        migrations.RemoveField(
            model_name='salesinvoicereportshipment',
            name='shipment_ref',
        ),
        migrations.AddIndex(
            model_name='salesinvoicereportshipment',
            index=models.Index(fields=['shipment'], name='sir_shipment_fk_idx'),
        ),
        migrations.RemoveIndex(
            model_name='salesinvoicereportsurcharge',
            name='sir_surcharge_trx_ref_idx',
        ),
        migrations.RemoveField(
            model_name='salesinvoicereportsurcharge',
            name='booking_ref',
        ),
        migrations.RemoveField(
            model_name='salesinvoicereportsurcharge',
            name='shipment_ref',
        ),
        migrations.RemoveField(
            model_name='salesinvoicereportsurcharge',
            name='surcharge_trx_ref',
        ),
        migrations.AddIndex(
            model_name='salesinvoicereportsurcharge',
            index=models.Index(fields=['surcharge'], name='sir_surcharge_fk_idx'),
        ),
    ]
