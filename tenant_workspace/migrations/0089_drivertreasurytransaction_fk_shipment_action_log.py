# Driver treasury transaction: related_shipment CharField -> shipment FK + action log FK.

from django.db import migrations, models
import django.db.models.deletion


def backfill_shipment_fk(apps, schema_editor):
    DriverTreasuryTransaction = apps.get_model(
        'tenant_workspace', 'DriverTreasuryTransaction'
    )
    TenantShipment = apps.get_model('tenant_workspace', 'TenantShipment')

    for txn in DriverTreasuryTransaction.objects.exclude(
        related_shipment=''
    ).iterator():
        ref = (txn.related_shipment or '').strip()
        if not ref:
            continue
        shipment = TenantShipment.objects.filter(shipment_no__iexact=ref).first()
        if shipment is not None:
            txn.shipment_id = shipment.shipment_id
            txn.save(update_fields=['shipment_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0088_recalculate_driver_treasury_balances'),
    ]

    operations = [
        migrations.AddField(
            model_name='drivertreasurytransaction',
            name='shipment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='treasury_transactions',
                to='tenant_workspace.tenantshipment',
            ),
        ),
        migrations.AddField(
            model_name='drivertreasurytransaction',
            name='operation_action_log',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='treasury_transactions',
                to='tenant_workspace.tenantoperationactionlog',
            ),
        ),
        migrations.RunPython(
            backfill_shipment_fk,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='drivertreasurytransaction',
            name='related_shipment',
        ),
        migrations.AddIndex(
            model_name='drivertreasurytransaction',
            index=models.Index(
                fields=['shipment'],
                name='tenant_dtt_shipment_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='drivertreasurytransaction',
            index=models.Index(
                fields=['operation_action_log'],
                name='tenant_dtt_action_log_idx',
            ),
        ),
        migrations.AddConstraint(
            model_name='drivertreasurytransaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ('shipment__isnull', False),
                    ('transaction_category', 'Client Collection'),
                    ('transaction_type', 'Debit'),
                ),
                fields=('driver_treasury', 'shipment', 'transaction_category'),
                name='tenant_dtt_unique_cod_per_wallet_shipment',
            ),
        ),
    ]
