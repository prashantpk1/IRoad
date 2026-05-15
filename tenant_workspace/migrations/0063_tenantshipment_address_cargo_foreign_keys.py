# Generated manually for TenantShipment address/cargo FK fields.

from django.db import migrations, models
import django.db.models.deletion


def backfill_shipment_address_cargo_from_booking(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')

    for shipment in TenantShipment.objects.all().iterator():
        updates = {}
        booking = None
        if shipment.booking_id:
            booking = TenantBooking.objects.filter(pk=shipment.booking_id).first()
        if booking is None and (shipment.booking_no or '').strip():
            booking = TenantBooking.objects.filter(booking_no=shipment.booking_no).first()

        if booking is None:
            continue

        if not shipment.loading_address_id and booking.loading_address_id:
            updates['loading_address_id'] = booking.loading_address_id
        if not shipment.delivery_address_id and booking.delivery_address_id:
            updates['delivery_address_id'] = booking.delivery_address_id
        if not shipment.cargo_id and booking.cargo_id:
            updates['cargo_id'] = booking.cargo_id
        if not (shipment.cargo_booking_item or '').strip() and (booking.cargo_booking_item or '').strip():
            updates['cargo_booking_item'] = booking.cargo_booking_item
        if not shipment.cargo_weight and booking.cargo_weight:
            updates['cargo_weight'] = booking.cargo_weight
        if not (shipment.cargo_unit or '').strip() and (booking.cargo_unit or '').strip():
            updates['cargo_unit'] = booking.cargo_unit
        if not shipment.cargo_qty and booking.cargo_qty:
            updates['cargo_qty'] = booking.cargo_qty

        if updates:
            TenantShipment.objects.filter(pk=shipment.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0062_tenantshipment_foreign_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipment',
            name='loading_address',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='shipments_as_loading',
                to='tenant_workspace.tenantaddressmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='delivery_address',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='shipments_as_delivery',
                to='tenant_workspace.tenantaddressmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='cargo_booking_item',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='cargo',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='shipments',
                to='tenant_workspace.tenantcargomaster',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='cargo_weight',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='cargo_unit',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='cargo_qty',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.RunPython(backfill_shipment_address_cargo_from_booking, migrations.RunPython.noop),
    ]
