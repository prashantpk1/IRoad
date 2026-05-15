# Generated manually for TenantTruckMovementLog FK linkage.

import uuid

from django.db import migrations, models
import django.db.models.deletion


def _driver_code_from_ref(value):
    value = (value or '').strip()
    if not value:
        return ''
    for separator in (' - ', ' — ', ' – '):
        if separator in value:
            return value.split(separator, 1)[0].strip()
    return value


def backfill_truck_movement_foreign_keys(apps, schema_editor):
    TenantTruckMovementLog = apps.get_model('tenant_workspace', 'TenantTruckMovementLog')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TruckMaster = apps.get_model('tenant_workspace', 'TruckMaster')
    DriverMaster = apps.get_model('tenant_workspace', 'DriverMaster')
    TenantLocationMaster = apps.get_model('tenant_workspace', 'TenantLocationMaster')

    for movement in TenantTruckMovementLog.objects.all().iterator():
        updates = {}

        booking_no = (movement.booking_ref or '').strip()
        if booking_no:
            booking = TenantBooking.objects.filter(booking_no=booking_no).first()
            if booking:
                updates['booking_id'] = booking.booking_id

        shipment_no = (movement.shipment_ref or '').strip()
        if shipment_no:
            shipment = TenantShipment.objects.filter(shipment_no=shipment_no).first()
            if shipment:
                updates['shipment_id'] = shipment.shipment_id
                if not updates.get('booking_id') and (shipment.booking_no or '').strip():
                    booking = TenantBooking.objects.filter(
                        booking_no=(shipment.booking_no or '').strip(),
                    ).first()
                    if booking:
                        updates['booking_id'] = booking.booking_id

        truck_code = (movement.truck_ref or '').strip()
        if truck_code:
            truck = TruckMaster.objects.filter(truck_code__iexact=truck_code).first()
            if truck is None:
                try:
                    truck_uuid = uuid.UUID(truck_code)
                except ValueError:
                    truck_uuid = None
                if truck_uuid:
                    truck = TruckMaster.objects.filter(truck_id=truck_uuid).first()
            if truck:
                updates['truck_id'] = truck.truck_id

        driver_code = _driver_code_from_ref(movement.driver_ref)
        if driver_code:
            driver = DriverMaster.objects.filter(driver_code__iexact=driver_code).first()
            if driver is None:
                try:
                    driver_uuid = uuid.UUID((movement.driver_ref or '').strip())
                except ValueError:
                    driver_uuid = None
                if driver_uuid:
                    driver = DriverMaster.objects.filter(driver_id=driver_uuid).first()
            if driver:
                updates['driver_id'] = driver.driver_id

        for field_name, raw_value in (
            ('from_location_point_id', movement.from_location),
            ('to_location_point_id', movement.to_location),
        ):
            label = (raw_value or '').strip()
            if not label:
                continue
            location = None
            try:
                location_uuid = uuid.UUID(label)
            except ValueError:
                location_uuid = None
            if location_uuid:
                location = TenantLocationMaster.objects.filter(location_id=location_uuid).first()
            if location is None:
                location = TenantLocationMaster.objects.filter(display_label__iexact=label).first()
            if location is None:
                location = TenantLocationMaster.objects.filter(
                    location_name_english__iexact=label,
                ).first()
            if location:
                updates[field_name] = location.location_id

        if updates:
            TenantTruckMovementLog.objects.filter(pk=movement.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0060_remove_pod_truck_driver_display'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='truck_movements',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='truck_movements',
                to='tenant_workspace.tenantshipment',
            ),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='truck',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='truck_movements',
                to='tenant_workspace.truckmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='driver',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='truck_movements',
                to='tenant_workspace.drivermaster',
            ),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='from_location_point',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movements_from',
                to='tenant_workspace.tenantlocationmaster',
            ),
        ),
        migrations.AddField(
            model_name='tenanttruckmovementlog',
            name='to_location_point',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movements_to',
                to='tenant_workspace.tenantlocationmaster',
            ),
        ),
        migrations.RunPython(backfill_truck_movement_foreign_keys, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(fields=['booking'], name='tenant_tml_booking_idx'),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(fields=['shipment'], name='tenant_tml_shipment_idx'),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(fields=['truck'], name='tenant_tml_truck_idx'),
        ),
        migrations.AddIndex(
            model_name='tenanttruckmovementlog',
            index=models.Index(fields=['driver'], name='tenant_tml_driver_idx'),
        ),
    ]
