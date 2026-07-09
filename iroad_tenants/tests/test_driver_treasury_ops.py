"""Driver treasury ledger convention: Credit = balance up, Debit = balance down."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.driver_treasury_ops import (
    expected_transaction_type,
    post_cod_collection_for_action9,
    validate_transaction_type_category,
)
from tenant_workspace.models import DriverTreasuryTransaction


class DriverTreasuryTypeMappingTests(SimpleTestCase):
    def test_client_collection_is_credit(self):
        self.assertEqual(
            expected_transaction_type('Client Collection'),
            DriverTreasuryTransaction.TransactionType.CREDIT,
        )

    def test_custody_collection_is_debit(self):
        self.assertEqual(
            expected_transaction_type('Custody Collection'),
            DriverTreasuryTransaction.TransactionType.DEBIT,
        )

    def test_validate_rejects_mismatched_pair(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            validate_transaction_type_category(
                DriverTreasuryTransaction.TransactionType.DEBIT,
                DriverTreasuryTransaction.TransactionCategory.CLIENT_COLLECTION,
            )


class DriverTreasuryBalanceFormulaTests(SimpleTestCase):
    def test_recalculate_balance_credit_minus_debit(self):
        treasury = MagicMock()
        credit_qs = MagicMock()
        debit_qs = MagicMock()
        credit_qs.aggregate.return_value = {'total': Decimal('1500.00')}
        debit_qs.aggregate.return_value = {'total': Decimal('500.00')}

        def filter_side_effect(**kwargs):
            txn_type = kwargs.get('transaction_type')
            if txn_type == DriverTreasuryTransaction.TransactionType.CREDIT:
                return credit_qs
            return debit_qs

        treasury.transactions.filter.side_effect = filter_side_effect

        from tenant_workspace.models import DriverTreasury

        DriverTreasury.recalculate_balance(treasury)
        self.assertEqual(treasury.current_balance, Decimal('1000.00'))
        treasury.save.assert_called_once_with(update_fields=['current_balance'])


class PostCodCollectionTests(SimpleTestCase):
    @patch('iroad_tenants.driver_treasury_ops.DriverTreasuryTransaction.objects.create')
    @patch('iroad_tenants.views._next_auto_number_for_form')
    @patch('iroad_tenants.driver_treasury_ops.cod_client_collection_exists', return_value=False)
    @patch('iroad_tenants.driver_treasury_ops.ensure_active_driver_treasury')
    def test_action9_posts_credit_client_collection(
        self,
        mock_ensure_treasury,
        _mock_exists,
        mock_next_no,
        mock_create,
    ):
        mock_next_no.return_value = ('TT-000001', 1)
        treasury = MagicMock()
        treasury.driver_id = 'driver-1'
        mock_ensure_treasury.return_value = treasury

        driver = MagicMock()
        driver.driver_code = 'DR-000001'
        driver.pk = 'driver-1'
        shipment = MagicMock()
        shipment.order_type = 'COD'
        shipment.driver = driver
        shipment.driver_id = 'driver-1'
        shipment.cod_amount = Decimal('1500.00')
        shipment.shipment_no = 'SH-000001'
        action_log = MagicMock()
        action_log.log_no = 'AL-000001'
        action_log.log_date = None

        post_cod_collection_for_action9(
            shipment=shipment,
            action_log=action_log,
            amount=Decimal('1500.00'),
        )

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(
            kwargs['transaction_type'],
            DriverTreasuryTransaction.TransactionType.CREDIT,
        )
        self.assertEqual(
            kwargs['transaction_category'],
            DriverTreasuryTransaction.TransactionCategory.CLIENT_COLLECTION,
        )
