# Generated manually for TenantShipmentSurcharge FK linkage.

from datetime import date
from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def backfill_shipment_surcharge_foreign_keys(apps, schema_editor):
    TenantShipmentSurcharge = apps.get_model('tenant_workspace', 'TenantShipmentSurcharge')
    TenantServiceItemMaster = apps.get_model('tenant_workspace', 'TenantServiceItemMaster')

    service_by_name = {
        (service.english_name or '').strip().lower(): service.service_item_id
        for service in TenantServiceItemMaster.objects.all().iterator()
    }

    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')

    for surcharge in TenantShipmentSurcharge.objects.all().iterator():
        updates = {}
        shipment = TenantShipment.objects.filter(pk=surcharge.shipment_id).first()
        if shipment is None:
            continue
        if shipment.booking_id:
            updates['booking_id'] = shipment.booking_id
        if shipment.client_account_id:
            updates['client_account_id'] = shipment.client_account_id

        item_label = (surcharge.item_label or '').strip()
        if item_label and not surcharge.service_item_id:
            base_label = item_label.split(' - ', 1)[0].strip().lower()
            service_id = service_by_name.get(base_label)
            if service_id:
                updates['service_item_id'] = service_id
            if ' - ' in item_label and not surcharge.description:
                updates['description'] = item_label.split(' - ', 1)[1].strip()[:255]

        qty = Decimal(surcharge.qty or 0)
        subtotal = Decimal(surcharge.subtotal or 0)
        if qty > 0 and not surcharge.unit_price:
            updates['unit_price'] = (subtotal / qty).quantize(Decimal('0.01'))

        if not surcharge.transaction_date:
            updates['transaction_date'] = (
                surcharge.created_at.date() if surcharge.created_at else date.today()
            )

        if updates:
            TenantShipmentSurcharge.objects.filter(pk=surcharge.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0064_tenantshipmentdocument_foreign_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='transaction_date',
            field=models.DateField(default=date.today),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('confirmed', 'Confirmed'),
                    ('invoiced', 'Invoiced'),
                    ('cancelled', 'Cancelled'),
                ],
                default='draft',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipment_surcharges',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='client_account',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipment_surcharges',
                to='tenant_workspace.tenantclientaccount',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='service_item',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipment_surcharges',
                to='tenant_workspace.tenantserviceitemmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='description',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='unit_price',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='currency',
            field=models.CharField(blank=True, default='SAR', max_length=8),
        ),
        migrations.AddField(
            model_name='tenantshipmentsurcharge',
            name='reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.RunPython(backfill_shipment_surcharge_foreign_keys, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenantshipmentsurcharge',
            index=models.Index(fields=['shipment'], name='tenant_surcharge_shipment_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentsurcharge',
            index=models.Index(fields=['service_item'], name='tenant_surcharge_service_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentsurcharge',
            index=models.Index(fields=['booking'], name='tenant_surcharge_booking_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentsurcharge',
            index=models.Index(fields=['client_account'], name='tenant_surcharge_client_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipmentsurcharge',
            index=models.Index(fields=['status'], name='tenant_surcharge_status_idx'),
        ),
    ]
