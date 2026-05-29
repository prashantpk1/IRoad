"""
Tests for driver Wallet list and transaction detail APIs.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.rbac import request_has_capability
from mobile_api.wallet.exceptions import WalletError
from mobile_api.wallet.services.wallet_service import WalletService, parse_wallet_date
from mobile_api.wallet.views.wallet_detail_view import WalletTransactionDetailAPIView
from mobile_api.wallet.views.wallet_list_view import WalletListAPIView


def _jwt_payload(*, schema='tenant_test', driver_id=None):
    return {
        'user_id': str(uuid4()),
        'tenant_schema': schema,
        'driver_id': str(driver_id or uuid4()),
        'role_name': 'Driver',
        'email': 'driver@test.com',
        'jti': str(uuid4()),
    }


def _driver(pk=None):
    d = MagicMock()
    d.pk = pk or uuid4()
    d.driver_id = d.pk
    d.driver_status = 'Active'
    return d


class WalletServiceValidationTests(SimpleTestCase):
    def test_parse_wallet_date_iso(self):
        self.assertEqual(parse_wallet_date('2026-02-10'), date(2026, 2, 10))

    def test_parse_wallet_date_dd_mm_yyyy(self):
        self.assertEqual(parse_wallet_date('15-08-1992'), date(1992, 8, 15))

    def test_parse_wallet_date_invalid(self):
        with self.assertRaises(WalletError) as ctx:
            parse_wallet_date('not-a-date')
        self.assertEqual(ctx.exception.code, 'invalid_date')


class WalletRbacTests(SimpleTestCase):
    def test_driver_has_wallet_capability(self):
        factory = APIRequestFactory()
        request = factory.get('/api/v1/mobile/driver/wallet/')
        payload = _jwt_payload()
        request.user = MobileUser(payload)
        request.auth = payload
        self.assertTrue(request_has_capability(request, 'mobile.driver.wallet'))


class WalletListViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = WalletListAPIView.as_view()
        self.driver = _driver()

    @patch('mobile_api.wallet.views.wallet_list_view.WalletService.list_wallet')
    @patch('mobile_api.wallet.views.wallet_list_view.resolve_job_detail_driver')
    def test_list_success(self, mock_resolve, mock_list):
        from mobile_api.wallet.selectors.wallet_query import WalletListPage

        mock_resolve.return_value = (self.driver, None, None)
        mock_list.return_value = WalletListPage(
            summary={'total_cash_collected': '10500.00', 'currency': 'SAR'},
            items=[{'transaction_no': 'TT-000001', 'amount': '4500.00'}],
            count=1,
            results_found=1,
        )

        request = self.factory.get(
            '/api/v1/mobile/driver/wallet/',
            {'shipment_no': 'SH-2026-1001'},
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 1)
        self.assertEqual(response.data['data']['summary']['currency'], 'SAR')
        self.assertEqual(len(response.data['data']['items']), 1)

    @patch('mobile_api.wallet.views.wallet_list_view.WalletService.list_wallet')
    @patch('mobile_api.wallet.views.wallet_list_view.resolve_job_detail_driver')
    def test_filter_preview_count_only(self, mock_resolve, mock_list):
        from mobile_api.wallet.selectors.wallet_query import WalletListPage

        mock_resolve.return_value = (self.driver, None, None)
        mock_list.return_value = WalletListPage(
            summary={'total_cash_collected': '10500.00'},
            items=[],
            count=0,
            results_found=2,
        )

        request = self.factory.get(
            '/api/v1/mobile/driver/wallet/',
            {'count_only': 'true', 'shipment_no': 'SH'},
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['results_found'], 2)
        self.assertEqual(response.data['data']['items'], [])


class WalletDetailProjectionTests(SimpleTestCase):
    def test_build_wallet_transaction_detail_resolves_shipment_route(self):
        from mobile_api.wallet.projections.wallet_detail_projection import (
            build_wallet_transaction_detail,
        )

        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_no = 'SH-W001'
        shipment.shipment_status = 'Closed'
        shipment.order_type = 'COD'
        shipment.booking_item_type = 'Outbound'
        shipment.shipment_date = date(2026, 2, 10)
        shipment.route_display = 'Jeddah Warehouse -> Riyadh Depot'
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.truck = None
        shipment.booking = None
        shipment.client_account = None

        txn = MagicMock()
        txn.shipment = shipment
        txn.pk = uuid4()
        txn.transaction_id = txn.pk
        txn.transaction_no = 'TT-000001'
        txn.amount = 4500
        txn.transaction_date = None
        txn.transaction_category = 'Client Collection'
        txn.transaction_type = 'Debit'
        txn.description = 'COD collection'

        payload = build_wallet_transaction_detail(txn)
        self.assertEqual(payload['shipment']['route']['route_display_start'], 'Jeddah Warehouse')
        self.assertEqual(payload['shipment']['route']['route_display_end'], 'Riyadh Depot')
        self.assertEqual(payload['shipment']['origin']['city'], 'Jeddah Warehouse')
        self.assertEqual(payload['shipment']['order_type'], 'COD')


class WalletDetailViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = WalletTransactionDetailAPIView.as_view()
        self.driver = _driver()
        self.transaction_id = str(uuid4())

    @patch('mobile_api.wallet.views.wallet_detail_view.WalletService.get_transaction_detail')
    @patch('mobile_api.wallet.views.wallet_detail_view.resolve_job_detail_driver')
    def test_detail_success(self, mock_resolve, mock_detail):
        mock_resolve.return_value = (self.driver, None, None)
        mock_detail.return_value = {
            'summary': {
                'transaction_no': 'TT-000001',
                'transaction_type_label': 'Received Amount',
                'amount': '4500.00',
                'currency': 'SAR',
                'read_only': True,
            },
            'transaction': {'shipment_no': 'SH-2026-1001'},
            'shipment': {'shipment_no': 'SH-2026-1001'},
            'description': 'COD collection',
            'wallet_projection_version': '1',
            'read_only': True,
        }

        request = self.factory.get(
            f'/api/v1/mobile/driver/wallet/transactions/{self.transaction_id}/',
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request, transaction_id=self.transaction_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['summary']['transaction_type_label'], 'Received Amount')
        self.assertTrue(response.data['data']['read_only'])

    @patch('mobile_api.wallet.views.wallet_detail_view.WalletService.get_transaction_detail')
    @patch('mobile_api.wallet.views.wallet_detail_view.resolve_job_detail_driver')
    def test_detail_not_found(self, mock_resolve, mock_detail):
        mock_resolve.return_value = (self.driver, None, None)
        mock_detail.side_effect = WalletError(
            'not found',
            code='transaction_not_found',
            http_status=404,
            message_key='mobile.wallet.transaction_not_found',
        )

        request = self.factory.get(
            f'/api/v1/mobile/driver/wallet/transactions/{self.transaction_id}/',
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request, transaction_id=self.transaction_id)
        self.assertEqual(response.status_code, 404)
