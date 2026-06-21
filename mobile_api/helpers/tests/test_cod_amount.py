from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mobile_api.helpers.cod_amount import (
    build_cod_payment_display,
    resolve_expected_cod_amount,
)
from mobile_api.utils.next_action_hint_builder import build_next_action_hint


class CodAmountHelperTests(SimpleTestCase):
    def test_shipment_cod_amount_wins(self):
        shipment = MagicMock()
        shipment.cod_amount = Decimal('100.00')
        shipment.order_type = 'COD'
        booking = MagicMock()
        booking.booking_line_cod_amount = Decimal('999.00')
        self.assertEqual(
            resolve_expected_cod_amount(shipment=shipment, booking=booking),
            Decimal('100.00'),
        )

    def test_falls_back_to_booking_line_outbound(self):
        shipment = MagicMock()
        shipment.cod_amount = Decimal('0')
        shipment.order_type = 'COD'
        shipment.booking_item_type = 'Outbound'
        booking = MagicMock()
        booking.booking_line_cod_amount = Decimal('250.50')
        booking.booking_line_backload_cod_amount = Decimal('999.00')
        self.assertEqual(
            resolve_expected_cod_amount(shipment=shipment, booking=booking),
            Decimal('250.50'),
        )

    def test_build_display_credit_empty(self):
        shipment = MagicMock()
        shipment.order_type = 'Credit'
        self.assertEqual(build_cod_payment_display(shipment=shipment), {})

    def test_build_display_cod(self):
        shipment = MagicMock()
        shipment.cod_amount = Decimal('100.00')
        shipment.order_type = 'COD'
        display = build_cod_payment_display(shipment=shipment)
        self.assertEqual(display['amount_due'], '100.00')
        self.assertEqual(display['expected_cod_amount'], '100.00')
        self.assertEqual(display['currency'], 'SAR')
        self.assertFalse(display['field_configuration']['comment_required'])
        self.assertFalse(display['field_configuration']['attachment_required'])
        self.assertEqual(display['collection_rules']['minimum_amount'], '100.00')
        self.assertTrue(display['collection_rules']['allow_over_collection'])

    def test_next_action_hint_includes_amount_for_a9(self):
        shipment = MagicMock()
        shipment.cod_amount = Decimal('100.00')
        shipment.order_type = 'COD'
        shipment.shipment_status = 'Delivered'
        hint = build_next_action_hint(
            workflow={
                'allowed_actions': [],
                'next_action': {'action_code': 'A9'},
            },
            pod_cod={'cod_collected': False, 'cod_pending': False},
            order_type='COD',
            shipment=shipment,
        )
        self.assertEqual(hint['screen'], 'collect_payment')
        self.assertEqual(hint['amount_due'], '100.00')
