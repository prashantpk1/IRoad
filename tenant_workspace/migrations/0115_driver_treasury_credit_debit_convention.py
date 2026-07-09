# Align driver wallet ledger: Credit = cash in, Debit = cash out (rules 7.3 / 7.4).

from decimal import Decimal

from django.db import migrations, models
from django.db.models import Sum


def flip_treasury_transaction_types(apps, schema_editor):
    DriverTreasuryTransaction = apps.get_model(
        'tenant_workspace', 'DriverTreasuryTransaction'
    )
    DriverTreasuryTransaction.objects.filter(
        transaction_category='Client Collection',
        transaction_type='Debit',
    ).update(transaction_type='Credit')
    DriverTreasuryTransaction.objects.filter(
        transaction_category='Custody Collection',
        transaction_type='Credit',
    ).update(transaction_type='Debit')


def recalculate_all_treasury_balances(apps, schema_editor):
    DriverTreasury = apps.get_model('tenant_workspace', 'DriverTreasury')
    DriverTreasuryTransaction = apps.get_model(
        'tenant_workspace', 'DriverTreasuryTransaction'
    )

    for treasury in DriverTreasury.objects.all().iterator():
        credits = (
            DriverTreasuryTransaction.objects.filter(
                driver_treasury_id=treasury.treasury_id,
                transaction_type='Credit',
            ).aggregate(total=Sum('amount'))['total']
            or Decimal('0.00')
        )
        debits = (
            DriverTreasuryTransaction.objects.filter(
                driver_treasury_id=treasury.treasury_id,
                transaction_type='Debit',
            ).aggregate(total=Sum('amount'))['total']
            or Decimal('0.00')
        )
        treasury.current_balance = credits - debits
        treasury.save(update_fields=['current_balance'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0114_tenantshipmentpodpage_attachment_storage_path'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='drivertreasurytransaction',
            name='tenant_dtt_unique_cod_per_wallet_shipment',
        ),
        migrations.RunPython(
            flip_treasury_transaction_types,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='drivertreasurytransaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ('shipment__isnull', False),
                    ('transaction_category', 'Client Collection'),
                    ('transaction_type', 'Credit'),
                ),
                fields=('driver_treasury', 'shipment', 'transaction_category'),
                name='tenant_dtt_unique_cod_per_wallet_shipment',
            ),
        ),
        migrations.RunPython(
            recalculate_all_treasury_balances,
            migrations.RunPython.noop,
        ),
    ]
