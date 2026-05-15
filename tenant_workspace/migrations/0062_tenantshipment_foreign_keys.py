# Generated manually for TenantShipment FK linkage.

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


def backfill_shipment_foreign_keys(apps, schema_editor):
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')
    TenantBooking = apps.get_model('tenant_workspace', 'TenantBooking')
    TenantClientAccount = apps.get_model('tenant_workspace', 'TenantClientAccount')
    DriverMaster = apps.get_model('tenant_workspace', 'DriverMaster')

    for shipment in TenantShipment.objects.all().iterator():
        updates = {}

        booking_no = (shipment.booking_no or '').strip()
        if booking_no:
            booking = TenantBooking.objects.filter(booking_no=booking_no).first()
            if booking:
                updates['booking_id'] = booking.booking_id
                if not shipment.client_account_ref:
                    updates['client_account_id'] = booking.client_account_id

        client_ref = (shipment.client_account_ref or '').strip()
        if not updates.get('client_account_id') and client_ref:
            account_no = client_ref.split(' - ', 1)[0].strip()
            client = TenantClientAccount.objects.filter(account_no=account_no).first()
            if client:
                updates['client_account_id'] = client.account_id

        driver_code = _driver_code_from_ref(shipment.driver_ref)
        if driver_code:
            driver = DriverMaster.objects.filter(driver_code__iexact=driver_code).first()
            if driver:
                updates['driver_id'] = driver.driver_id

        if updates:
            TenantShipment.objects.filter(pk=shipment.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0061_tenanttruckmovementlog_foreign_keys'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantshipment',
            name='booking',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipments',
                to='tenant_workspace.tenantbooking',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='client_account',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipments',
                to='tenant_workspace.tenantclientaccount',
            ),
        ),
        migrations.AddField(
            model_name='tenantshipment',
            name='driver',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='shipments',
                to='tenant_workspace.drivermaster',
            ),
        ),
        migrations.RunPython(backfill_shipment_foreign_keys, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(fields=['booking'], name='tenant_shipment_booking_fk_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(fields=['client_account'], name='tenant_shipment_client_fk_idx'),
        ),
        migrations.AddIndex(
            model_name='tenantshipment',
            index=models.Index(fields=['driver'], name='tenant_shipment_driver_fk_idx'),
        ),
    ]
