"""
Driver Treasury operational helpers (IRoute Ch.13).

Maps UI categories to ledger types:
  Client Collection  -> Debit  (COD cash into driver wallet)
  Custody Collection -> Credit (cash handed to custody / transfer out)
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from tenant_workspace.models import (
    DriverTreasury,
    DriverTreasuryTransaction,
    DriverMaster,
    TenantShipment,
)

DRIVER_TREASURY_AUTO_FORM_CODE = 'driver-treasury'
DRIVER_TREASURY_AUTO_FORM_LABEL = 'Driver Treasury'
DRIVER_TREASURY_REF_PREFIX = 'DTR'

DRIVER_TXN_AUTO_FORM_CODE = 'driver-treasury-transaction'
DRIVER_TXN_AUTO_FORM_LABEL = 'Driver Treasury Transactions'
DRIVER_TXN_REF_PREFIX = 'TT'

_CATEGORY_TO_TYPE = {
    DriverTreasuryTransaction.TransactionCategory.CLIENT_COLLECTION: (
        DriverTreasuryTransaction.TransactionType.DEBIT
    ),
    DriverTreasuryTransaction.TransactionCategory.CUSTODY_COLLECTION: (
        DriverTreasuryTransaction.TransactionType.CREDIT
    ),
}


def expected_transaction_type(transaction_category: str) -> str | None:
    return _CATEGORY_TO_TYPE.get(transaction_category)


def validate_transaction_type_category(
    transaction_type: str,
    transaction_category: str,
) -> None:
    expected = expected_transaction_type(transaction_category)
    if expected and transaction_type != expected:
        raise ValidationError(
            {
                'transaction_type': (
                    f'{transaction_category} requires transaction type '
                    f'{expected}.'
                ),
            }
        )


def validate_shipment_for_treasury(
    shipment: TenantShipment | None,
    driver_treasury: DriverTreasury | None,
) -> None:
    if shipment is None or driver_treasury is None:
        return
    shipment_driver_id = shipment.driver_id
    treasury_driver_id = driver_treasury.driver_id
    if (
        shipment_driver_id
        and treasury_driver_id
        and shipment_driver_id != treasury_driver_id
    ):
        raise ValidationError(
            {
                'shipment': (
                    'Shipment driver must match the treasury wallet driver.'
                ),
            }
        )


def ensure_active_driver_treasury(
    driver: DriverMaster,
    *,
    auto_create: bool = True,
) -> DriverTreasury | None:
    if driver is None:
        return None
    treasury = (
        DriverTreasury.objects.filter(
            driver=driver,
            status=DriverTreasury.Status.ACTIVE,
        )
        .order_by('-created_at')
        .first()
    )
    if treasury is not None:
        return treasury
    if not auto_create:
        return None
    from iroad_tenants.views import (  # lazy: auto-number helpers live in views
        _next_auto_number_for_form,
    )

    code, seq = _next_auto_number_for_form(
        form_code=DRIVER_TREASURY_AUTO_FORM_CODE,
        form_label=DRIVER_TREASURY_AUTO_FORM_LABEL,
        prefix=DRIVER_TREASURY_REF_PREFIX,
    )
    return DriverTreasury.objects.create(
        treasury_code=code,
        treasury_sequence=seq,
        driver=driver,
        status=DriverTreasury.Status.ACTIVE,
        current_balance=Decimal('0.00'),
    )


def cod_client_collection_exists(
    *,
    shipment: TenantShipment,
    driver_treasury: DriverTreasury,
) -> bool:
    if shipment is None:
        return False
    return DriverTreasuryTransaction.objects.filter(
        driver_treasury=driver_treasury,
        shipment=shipment,
        transaction_category=(
            DriverTreasuryTransaction.TransactionCategory.CLIENT_COLLECTION
        ),
        transaction_type=DriverTreasuryTransaction.TransactionType.DEBIT,
    ).exists()


def post_cod_collection_for_action9(
    *,
    shipment: TenantShipment,
    action_log,
    amount: Decimal | None = None,
) -> DriverTreasuryTransaction | None:
    """
    Action 9 (Collect Payment): Debit · Client Collection on driver wallet.
    Idempotent per shipment + treasury (DB unique constraint).
    """
    if shipment is None:
        return None
    if (shipment.order_type or '').upper() != 'COD':
        return None

    driver = shipment.driver
    if driver is None and action_log is not None:
        driver = getattr(action_log, 'driver', None)
    if driver is None:
        raise ValidationError(
            'COD collection requires a driver on the shipment or action log.'
        )

    treasury = ensure_active_driver_treasury(driver, auto_create=True)
    if treasury is None:
        raise ValidationError(
            f'No active Driver Treasury wallet for driver {driver.driver_code}.'
        )

    validate_shipment_for_treasury(shipment, treasury)

    if cod_client_collection_exists(
        shipment=shipment,
        driver_treasury=treasury,
    ):
        return None

    collected = amount
    if collected is None:
        collected = shipment.cod_amount or Decimal('0.00')
    collected = Decimal(str(collected))
    if collected <= 0:
        raise ValidationError(
            'COD collection amount must be greater than zero.'
        )

    from iroad_tenants.views import _next_auto_number_for_form

    txn_no, txn_seq = _next_auto_number_for_form(
        form_code=DRIVER_TXN_AUTO_FORM_CODE,
        form_label=DRIVER_TXN_AUTO_FORM_LABEL,
        prefix=DRIVER_TXN_REF_PREFIX,
    )
    log_no = getattr(action_log, 'log_no', '') or ''
    log_ref = f'Action 9 · {log_no}' if log_no else 'Action 9 · Collect Payment'
    txn_date = getattr(action_log, 'log_date', None) or timezone.now()
    shipment_no = shipment.shipment_no

    return DriverTreasuryTransaction.objects.create(
        transaction_no=txn_no,
        transaction_sequence=txn_seq,
        transaction_date=txn_date,
        driver_treasury=treasury,
        transaction_type=DriverTreasuryTransaction.TransactionType.DEBIT,
        transaction_category=(
            DriverTreasuryTransaction.TransactionCategory.CLIENT_COLLECTION
        ),
        amount=collected,
        shipment=shipment,
        operation_action_log=action_log,
        description=(
            f'{log_ref} · COD collection for shipment {shipment_no} '
            f'({collected:.2f})'
        ),
    )
