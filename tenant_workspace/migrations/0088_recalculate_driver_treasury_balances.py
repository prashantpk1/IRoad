# Recalculate wallet balances after debit/credit formula fix (Ch.13).

from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


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
        treasury.current_balance = debits - credits
        treasury.save(update_fields=['current_balance'])


class Migration(migrations.Migration):

    dependencies = [
        ('tenant_workspace', '0087_tenantshipmentpodpage_action_log_fk'),
    ]

    operations = [
        migrations.RunPython(
            recalculate_all_treasury_balances,
            migrations.RunPython.noop,
        ),
    ]
