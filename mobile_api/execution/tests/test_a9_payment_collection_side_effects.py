from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from iroad_tenants.services.cod_execution_service import CODExecutionService


class A9PaymentCollectionSideEffectTests(SimpleTestCase):
    def _shipment(self):
        shipment = MagicMock()
        shipment.order_type = 'COD'
        shipment.driver_id = 'drv-1'
        shipment.pk = 'ship-1'
        shipment.shipment_id = 'ship-1'
        shipment.collection_status = 'Pending'
        shipment.save = MagicMock()
        return shipment

    def _action_log(self):
        return SimpleNamespace(
            pk='log-1',
            log_id='log-1',
            driver_id='drv-1',
            idempotency_key='client-uuid-execute-1',
            log_no='OAL-9',
            log_date=None,
        )

    def _bundle(
        self,
        *,
        promotion_action_log_id: str = '',
        shipment_id: str = 'ship-1',
        variance_detected: bool = False,
        amount: Decimal = Decimal('100.00'),
        expected_amount: Decimal = Decimal('100.00'),
    ):
        return SimpleNamespace(
            tenant_schema='tenant-1',
            driver_id='drv-1',
            client_payment_id='client-uuid-execute-1',
            shipment_id=shipment_id,
            promotion_action_log_id=promotion_action_log_id,
            variance_detected=variance_detected,
            amount=amount,
            expected_amount=expected_amount,
            created_at=None,
        )

    def test_skips_post_when_bundle_already_consumed_by_same_action_log(self):
        bundle = self._bundle(promotion_action_log_id='log-1')
        shipment = self._shipment()
        action_log = self._action_log()

        with patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection, patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'iroad_tenants.services.cod_execution_service.post_cod_collection_for_action9',
        ) as post_mock, patch(
            'iroad_tenants.services.treasury_side_effects.consume_payment_collection_bundle_for_action9',
        ) as consume_mock:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            CODExecutionService.apply_collect_payment_side_effect(
                shipment=shipment,
                action_log=action_log,
                amount=Decimal('1.00'),
            )

        consume_mock.assert_not_called()
        post_mock.assert_not_called()

    def test_exact_collection_posts_actual_amount(self):
        bundle = self._bundle(promotion_action_log_id='')
        shipment = self._shipment()
        action_log = self._action_log()

        with patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection, patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'iroad_tenants.services.cod_execution_service.post_cod_collection_for_action9',
        ) as post_mock, patch(
            'iroad_tenants.services.treasury_side_effects.consume_payment_collection_bundle_for_action9',
        ) as consume_mock:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            CODExecutionService.apply_collect_payment_side_effect(
                shipment=shipment,
                action_log=action_log,
                amount=Decimal('1.00'),
            )

        consume_mock.assert_called_once()
        post_mock.assert_called_once()
        post_mock.assert_called_once_with(
            shipment=shipment,
            action_log=action_log,
            amount=Decimal('100.00'),
        )

    def test_short_collection_posts_actual_amount(self):
        bundle = self._bundle(
            promotion_action_log_id='',
            amount=Decimal('1400.00'),
            expected_amount=Decimal('1500.00'),
            variance_detected=True,
        )
        shipment = self._shipment()
        action_log = self._action_log()

        with patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection, patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'iroad_tenants.services.cod_execution_service.post_cod_collection_for_action9',
        ) as post_mock, patch(
            'iroad_tenants.services.treasury_side_effects.consume_payment_collection_bundle_for_action9',
        ) as consume_mock:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            CODExecutionService.apply_collect_payment_side_effect(
                shipment=shipment,
                action_log=action_log,
                amount=Decimal('1.00'),
            )

        consume_mock.assert_called_once()
        post_mock.assert_called_once_with(
            shipment=shipment,
            action_log=action_log,
            amount=Decimal('1400.00'),
        )

    def test_over_collection_posts_actual_amount(self):
        bundle = self._bundle(
            promotion_action_log_id='',
            amount=Decimal('1600.00'),
            expected_amount=Decimal('1500.00'),
            variance_detected=True,
        )
        shipment = self._shipment()
        action_log = self._action_log()

        with patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection, patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'iroad_tenants.services.cod_execution_service.post_cod_collection_for_action9',
        ) as post_mock, patch(
            'iroad_tenants.services.treasury_side_effects.consume_payment_collection_bundle_for_action9',
        ) as consume_mock:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            CODExecutionService.apply_collect_payment_side_effect(
                shipment=shipment,
                action_log=action_log,
                amount=Decimal('1.00'),
            )

        consume_mock.assert_called_once()
        post_mock.assert_called_once_with(
            shipment=shipment,
            action_log=action_log,
            amount=Decimal('1600.00'),
        )

    def test_duplicate_payment_is_blocked(self):
        bundle = self._bundle(promotion_action_log_id='')
        shipment = self._shipment()
        shipment.collection_status = 'Collected'
        action_log = self._action_log()

        with patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection, patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            with self.assertRaises(ValidationError) as exc:
                CODExecutionService.apply_collect_payment_side_effect(
                    shipment=shipment,
                    action_log=action_log,
                    amount=Decimal('1.00'),
                )

        self.assertIn('Payment already collected', str(exc.exception))

    def test_wrong_shipment_bundle_rejected(self):
        bundle = self._bundle(shipment_id='ship-other')
        shipment = self._shipment()
        action_log = self._action_log()

        with patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection, patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'iroad_tenants.services.cod_execution_service.post_cod_collection_for_action9',
        ) as post_mock, patch(
            'iroad_tenants.services.treasury_side_effects.consume_payment_collection_bundle_for_action9',
        ) as consume_mock:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            with self.assertRaises(ValidationError):
                CODExecutionService.apply_collect_payment_side_effect(
                    shipment=shipment,
                    action_log=action_log,
                    amount=Decimal('1.00'),
                )

        consume_mock.assert_not_called()
        post_mock.assert_not_called()

