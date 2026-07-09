"""
Tests for driver History list and detail APIs.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.history.exceptions import HistoryError
from mobile_api.history.selectors.history_query import HistoryListFilters, HistoryQuerySelector
from mobile_api.history.services.history_service import HistoryService, parse_history_date
from mobile_api.history.views.history_detail_view import HistoryDetailAPIView
from mobile_api.history.views.history_list_view import HistoryListAPIView
from mobile_api.rbac import request_has_capability
from tenant_workspace.models import TenantShipment


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


class HistoryServiceValidationTests(SimpleTestCase):
    def test_parse_history_date_iso(self):
        self.assertEqual(parse_history_date('2026-02-10'), date(2026, 2, 10))

    def test_parse_history_date_dd_mm_yyyy(self):
        self.assertEqual(parse_history_date('15-08-1992'), date(1992, 8, 15))

    def test_parse_history_date_invalid(self):
        with self.assertRaises(HistoryError) as ctx:
            parse_history_date('not-a-date')
        self.assertEqual(ctx.exception.code, 'invalid_date')


class HistoryRbacTests(SimpleTestCase):
    def test_driver_has_history_capability(self):
        factory = APIRequestFactory()
        request = factory.get('/api/v1/mobile/driver/history/')
        payload = _jwt_payload()
        request.user = MobileUser(payload)
        request.auth = payload
        self.assertTrue(request_has_capability(request, 'mobile.driver.history'))


class HistoryListViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = HistoryListAPIView.as_view()
        self.driver = _driver()

    @patch('mobile_api.history.views.history_list_view.HistoryService.list_history')
    @patch('mobile_api.history.views.history_list_view.resolve_job_detail_driver')
    def test_list_success(self, mock_resolve, mock_list):
        from mobile_api.history.selectors.history_query import HistoryListPage

        mock_resolve.return_value = (self.driver, None, None)
        mock_list.return_value = HistoryListPage(
            items=[{'shipment_no': 'SH-2026-1001'}],
            count=1,
            results_found=1,
            total_records=1,
            total_pages=1,
            current_page=1,
            page_size=10,
        )

        request = self.factory.get(
            '/api/v1/mobile/driver/history/',
            {'shipment_no': 'SH-2026-1001', 'date': '10-02-2026'},
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 1)
        self.assertEqual(len(response.data['data']['items']), 1)
        self.assertEqual(response.data['data']['results_found'], 1)
        self.assertEqual(response.data['data']['total_records'], 1)
        self.assertEqual(response.data['data']['current_page'], 1)

    @patch('mobile_api.history.views.history_list_view.HistoryService.list_history')
    @patch('mobile_api.history.views.history_list_view.resolve_job_detail_driver')
    def test_list_pagination_query_params(self, mock_resolve, mock_list):
        from mobile_api.history.selectors.history_query import HistoryListPage

        mock_resolve.return_value = (self.driver, None, None)
        mock_list.return_value = HistoryListPage(
            items=[],
            count=0,
            results_found=25,
            total_records=25,
            total_pages=3,
            current_page=2,
            page_size=10,
        )

        request = self.factory.get(
            '/api/v1/mobile/driver/history/',
            {'page': '2', 'page_size': '10'},
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        mock_list.assert_called_once()
        pagination = mock_list.call_args.kwargs['pagination']
        self.assertEqual(pagination.page, 2)
        self.assertEqual(pagination.page_size, 10)

    @patch('mobile_api.history.views.history_list_view.HistoryService.list_history')
    @patch('mobile_api.history.views.history_list_view.resolve_job_detail_driver')
    def test_filter_preview_count_only(self, mock_resolve, mock_list):
        from mobile_api.history.selectors.history_query import HistoryListPage

        mock_resolve.return_value = (self.driver, None, None)
        mock_list.return_value = HistoryListPage(
            items=[],
            count=0,
            results_found=3,
        )

        request = self.factory.get(
            '/api/v1/mobile/driver/history/',
            {'count_only': 'true', 'shipment_no': 'SH'},
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['results_found'], 3)
        self.assertEqual(response.data['data']['items'], [])


class HistoryDetailViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = HistoryDetailAPIView.as_view()
        self.driver = _driver()
        self.shipment_id = str(uuid4())

    @patch('mobile_api.history.views.history_detail_view.HistoryService.get_history_detail')
    @patch('mobile_api.history.views.history_detail_view.resolve_job_detail_driver')
    def test_detail_success(self, mock_resolve, mock_detail):
        mock_resolve.return_value = (self.driver, None, None)
        mock_detail.return_value = {
            'summary': {'booking_no': 'BK-000010', 'status': 'Completed'},
            'workflow_status': [{'step_key': 'pickup', 'completed': True}],
            'timeline': {'events': []},
            'actions_fired_count': 5,
            'history_projection_version': '1',
        }

        request = self.factory.get(
            f'/api/v1/mobile/driver/history/{self.shipment_id}/',
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request, shipment_id=self.shipment_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['summary']['booking_no'], 'BK-000010')
        self.assertEqual(len(response.data['data']['workflow_status']), 1)

    @patch('mobile_api.history.views.history_detail_view.HistoryService.get_history_detail')
    @patch('mobile_api.history.views.history_detail_view.resolve_job_detail_driver')
    def test_detail_not_completed(self, mock_resolve, mock_detail):
        mock_resolve.return_value = (self.driver, None, None)
        mock_detail.side_effect = HistoryError(
            'Job is not in history',
            code='history_not_available',
            http_status=400,
            message_key='mobile.history.not_completed',
        )

        request = self.factory.get(
            f'/api/v1/mobile/driver/history/{self.shipment_id}/',
        )
        payload = _jwt_payload(driver_id=self.driver.pk)
        force_authenticate(request, user=MobileUser(payload), token=payload)

        response = self.view(request, shipment_id=self.shipment_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['data']['error']['code'], 'history_not_available')


class HistoryCardProjectionTests(SimpleTestCase):
    def test_terminal_status_labels(self):
        from mobile_api.history.projections.history_card_projection import final_state_labels

        closed = MagicMock()
        closed.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        self.assertEqual(final_state_labels(closed), ('Completed', 'Closed'))

        cancelled = MagicMock()
        cancelled.shipment_status = TenantShipment.ShipmentStatus.CANCELLED
        self.assertEqual(final_state_labels(cancelled), ('Cancelled', 'Cancelled'))

    def test_payment_method_tag_reads_order_type_from_db(self):
        from mobile_api.history.projections.history_card_projection import payment_method_tag

        credit_shipment = MagicMock()
        credit_shipment.order_type = 'Credit'
        self.assertEqual(payment_method_tag(credit_shipment, None), 'Credit')

        cod_shipment = MagicMock()
        cod_shipment.order_type = 'COD'
        self.assertEqual(payment_method_tag(cod_shipment, None), 'COD')

        fallback_booking = MagicMock()
        fallback_booking.order_type = 'Credit'
        empty_shipment = MagicMock()
        empty_shipment.order_type = ''
        self.assertEqual(payment_method_tag(empty_shipment, fallback_booking), 'Credit')

    def test_resolve_history_route_aligns_route_with_address_cities(self):
        from mobile_api.history.projections.history_card_projection import resolve_history_route

        pickup = MagicMock()
        pickup.city = 'Riyadh'
        pickup.english_label = 'Main Warehouse, Riyadh'
        pickup.arabic_label = ''
        pickup.display_name = 'Main Warehouse, Riyadh'
        pickup.address_line_1 = 'Address line 2'
        pickup.address_line_2 = ''
        pickup.district = ''
        pickup.province = ''
        pickup.street = ''
        pickup.building_no = ''
        pickup.postal_code = ''
        pickup.map_link = ''
        pickup.contact_name = ''
        pickup.mobile_no_1 = ''
        pickup.mobile_no_2 = ''
        pickup.site_instructions = ''
        pickup.address_id = uuid4()
        pickup.address_code = 'AD-1'

        drop = MagicMock()
        drop.city = 'Jeddah'
        drop.english_label = 'Backload Drop, Jeddah'
        drop.arabic_label = ''
        drop.display_name = 'Backload Drop, Jeddah'
        drop.address_line_1 = 'Address line 2'
        drop.address_line_2 = ''
        drop.district = ''
        drop.province = ''
        drop.street = ''
        drop.building_no = ''
        drop.postal_code = ''
        drop.map_link = ''
        drop.contact_name = ''
        drop.mobile_no_1 = ''
        drop.mobile_no_2 = ''
        drop.site_instructions = ''
        drop.address_id = uuid4()
        drop.address_code = 'AD-2'

        origin = MagicMock()
        origin.display_label = 'jeddah'
        origin.location_name_english = 'jeddah'
        origin.location_name_arabic = ''
        destination = MagicMock()
        destination.display_label = 'Makkah'
        destination.location_name_english = 'Makkah'
        destination.location_name_arabic = ''

        route_master = MagicMock()
        route_master.route_id = uuid4()
        route_master.route_code = 'RT-1'
        route_master.route_label = 'jeddah — Makkah'
        route_master.route_type = 'Domestic'
        route_master.origin_point = origin
        route_master.destination_point = destination

        booking = MagicMock()
        booking.trip_type = 'Round'
        booking.route = route_master
        booking.route_direction = 'forward'
        booking.route_display = 'jeddah — Makkah'
        booking.loading_address = pickup
        booking.delivery_address = drop

        shipment = MagicMock()
        shipment.route_display = ''
        shipment.booking = booking
        shipment.booking_item_type = 'Backload'
        shipment.loading_address = pickup
        shipment.delivery_address = drop

        route = resolve_history_route(shipment, booking)
        self.assertEqual(route['origin_city'], 'Jeddah')
        self.assertEqual(route['destination_city'], 'Riyadh')
        self.assertIn('Jeddah', route['route_display'])
        self.assertIn('Riyadh', route['route_display'])

    def test_resolve_trip_type_from_booking(self):
        from mobile_api.history.projections.history_card_projection import resolve_trip_type

        booking = MagicMock()
        booking.trip_type = 'Round'
        shipment = MagicMock()
        shipment.trip_type = 'One-Way'
        self.assertEqual(resolve_trip_type(booking, shipment), 'Round')

    def test_resolve_trip_type_falls_back_to_shipment(self):
        from mobile_api.history.projections.history_card_projection import resolve_trip_type

        shipment = MagicMock()
        shipment.trip_type = 'One-Way'
        self.assertEqual(resolve_trip_type(None, shipment), 'One-Way')

    def test_route_type_label_round_trip(self):
        from mobile_api.history.projections.history_card_projection import route_type_label

        booking = MagicMock()
        booking.trip_type = 'Round'
        shipment = MagicMock()
        shipment.booking_item_type = 'Outbound'
        self.assertEqual(route_type_label(booking, shipment), 'Round')

    def test_route_type_label_inbound_leg(self):
        from mobile_api.history.projections.history_card_projection import route_type_label

        booking = MagicMock()
        booking.trip_type = 'One-Way'
        shipment = MagicMock()
        shipment.booking_item_type = 'Backload'
        self.assertEqual(route_type_label(booking, shipment), 'Inbound')

    def test_build_history_card_includes_trip_type(self):
        from mobile_api.history.projections.history_card_projection import build_history_card

        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_no = 'BK-001'
        booking.trip_type = 'One-Way'
        booking.route_display = ''
        booking.route = None
        booking.route_direction = ''

        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_no = 'SH-001'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.order_type = 'COD'
        shipment.shipment_date = date(2026, 2, 10)
        shipment.booking = booking
        shipment.booking_item_type = 'Outbound'
        shipment.route_display = ''
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.truck = None
        shipment.client_account = None
        shipment.trip_type = ''

        card = build_history_card(shipment)
        self.assertEqual(card['trip_type'], 'One-Way')

    def test_build_history_card_route_from_route_master(self):
        from mobile_api.history.projections.history_card_projection import build_history_card

        origin = MagicMock()
        origin.display_label = 'Alec Sexton4'
        origin.location_name_english = 'Alec Sexton4'
        origin.location_name_arabic = ''
        destination = MagicMock()
        destination.display_label = 'Goa'
        destination.location_name_english = 'Goa'
        destination.location_name_arabic = ''

        route_master = MagicMock()
        route_master.route_id = uuid4()
        route_master.route_code = 'RT-AAAB'
        route_master.route_label = 'delhi — Goa'
        route_master.route_type = 'Domestic'
        route_master.origin_point = origin
        route_master.destination_point = destination

        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_no = 'BK-001'
        booking.trip_type = 'Round'
        booking.route = route_master
        booking.route_direction = 'forward'
        booking.route_display = 'delhi — Goa'
        booking.loading_address = None
        booking.delivery_address = None

        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_no = 'SH-001'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.order_type = 'COD'
        shipment.shipment_date = date(2026, 2, 10)
        shipment.booking = booking
        shipment.booking_item_type = 'Outbound'
        shipment.route_display = ''
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.truck = None
        shipment.client_account = None
        shipment.trip_type = ''

        card = build_history_card(shipment)
        self.assertEqual(card['trip_type'], 'Round')
        self.assertEqual(card['route']['route_code'], 'RT-AAAB')
        self.assertEqual(card['route']['route_type'], 'Domestic')
        self.assertEqual(card['route']['route_display_start'], 'Alec Sexton4')
        self.assertEqual(card['route']['route_display_end'], 'Goa')
        self.assertEqual(card['route']['route_direction'], 'forward')

    def test_history_detail_summary_uses_order_type(self):
        from mobile_api.history.projections.history_detail_projection import build_history_detail

        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_no = 'SH-D004'
        shipment.order_type = 'Credit'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.shipment_date = None
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.route_display = 'Jeddah Warehouse → Riyadh Depot'
        shipment.booking = None
        shipment.truck = None
        shipment.booking_item_type = 'Outbound'

        payload = build_history_detail(shipment, [])
        self.assertEqual(payload['summary']['order_type'], 'Credit')
        self.assertEqual(payload['summary']['transaction_type'], 'Credit')
        self.assertEqual(payload['summary']['payment_method'], 'Credit')
        self.assertEqual(payload['summary']['route']['route_display_start'], 'Jeddah Warehouse')
        self.assertEqual(payload['summary']['route']['route_display_end'], 'Riyadh Depot')
        self.assertIn('→', payload['summary']['route_display'])

    def test_history_detail_resolves_truck_from_booking_assignment(self):
        from mobile_api.history.projections.history_detail_projection import build_history_detail

        truck = MagicMock()
        truck.pk = uuid4()
        truck.truck_id = truck.pk
        truck.truck_code = 'TRK-001'
        truck.plate_number = 'ABC 1234'

        booking = MagicMock()
        booking.assigned_truck = truck
        booking.booking_line_backload_truck = None
        booking.loading_address = None
        booking.delivery_address = None
        booking.route_display = ''

        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_no = 'SH-100'
        shipment.order_type = 'COD'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.shipment_date = None
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.route_display = ''
        shipment.truck = None
        shipment.booking = booking
        shipment.booking_item_type = 'Outbound'

        payload = build_history_detail(shipment, [])
        self.assertEqual(payload['summary']['truck']['truck_code'], 'TRK-001')
        self.assertEqual(payload['summary']['truck']['plate_number'], 'ABC 1234')

    def test_history_detail_includes_trip_type_and_addresses(self):
        from mobile_api.history.projections.history_detail_projection import (
            build_history_detail,
        )

        pickup = MagicMock()
        pickup.address_id = uuid4()
        pickup.address_code = 'AD-PICK'
        pickup.display_name = 'Warehouse A'
        pickup.english_label = 'Warehouse A'
        pickup.arabic_label = ''
        pickup.address_category = 'Warehouse'
        pickup.address_line_1 = 'Line 1'
        pickup.address_line_2 = ''
        pickup.city = 'Riyadh'
        pickup.province = ''
        pickup.district = ''
        pickup.street = ''
        pickup.building_no = ''
        pickup.postal_code = ''
        pickup.map_link = 'https://maps.example/pickup'
        pickup.contact_name = ''
        pickup.mobile_no_1 = ''
        pickup.mobile_no_2 = ''
        pickup.site_instructions = ''

        drop = MagicMock()
        drop.address_id = uuid4()
        drop.address_code = 'AD-DROP'
        drop.display_name = 'Customer B'
        drop.english_label = 'Customer B'
        drop.arabic_label = ''
        drop.address_category = 'Customer'
        drop.address_line_1 = 'Line 2'
        drop.address_line_2 = ''
        drop.city = 'Jeddah'
        drop.province = ''
        drop.district = ''
        drop.street = ''
        drop.building_no = ''
        drop.postal_code = ''
        drop.map_link = 'https://maps.example/drop'
        drop.contact_name = ''
        drop.mobile_no_1 = ''
        drop.mobile_no_2 = ''
        drop.site_instructions = ''

        booking = MagicMock()
        booking.booking_id = uuid4()
        booking.booking_no = 'BK-RT-001'
        booking.trip_type = 'Round'
        booking.route = None
        booking.route_display = ''
        booking.route_direction = ''
        booking.loading_address = pickup
        booking.delivery_address = drop

        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_id = shipment.pk
        shipment.shipment_no = 'SH-RT-001'
        shipment.order_type = 'Credit'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.shipment_date = None
        shipment.loading_address = pickup
        shipment.delivery_address = drop
        shipment.route_display = ''
        shipment.booking = booking
        shipment.truck = None
        shipment.booking_item_type = 'Outbound'
        shipment.trip_type = ''

        payload = build_history_detail(shipment, [])
        self.assertEqual(payload['trip_type'], 'Round')
        self.assertEqual(payload['pickup_address']['address_code'], 'AD-PICK')
        self.assertEqual(payload['pickup_address']['city'], 'Riyadh')
        self.assertEqual(payload['pickup_address']['map_link'], 'https://maps.example/pickup')
        self.assertEqual(payload['drop_address']['address_code'], 'AD-DROP')
        self.assertEqual(payload['drop_address']['city'], 'Jeddah')
        self.assertEqual(payload['drop_address']['map_link'], 'https://maps.example/drop')

    def test_workflow_loading_timestamp_precedes_delivery(self):
        from datetime import datetime, timezone

        from mobile_api.history.projections.history_detail_projection import (
            build_workflow_status,
        )

        booking = MagicMock()
        booking.order_type = 'COD'
        booking.loading_address = None
        booking.delivery_address = None
        booking.route_display = ''

        shipment = MagicMock()
        shipment.shipment_no = 'SH-0102'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.order_type = 'COD'
        shipment.collection_status = TenantShipment.CollectionStatus.COLLECTED
        shipment.pod_status = TenantShipment.PodStatus.COMPLETED
        shipment.booking = booking
        shipment.cargo = None
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.route_display = ''
        shipment.booking_item_type = 'Backload'

        t_load = datetime(2026, 6, 24, 15, 1, tzinfo=timezone.utc)
        t_confirm = datetime(2026, 6, 24, 15, 3, tzinfo=timezone.utc)
        t_delivery = datetime(2026, 6, 24, 15, 2, tzinfo=timezone.utc)

        def _action(code, label):
            action = MagicMock()
            action.action_code = code
            action.english_label = label
            action.arabic_label = ''
            action.shipment_status_impact = ''
            action.movement_status_impact = ''
            action.auto_pod_post = False
            action.auto_treasury_post = False
            action.sequence_category = ''
            action.admin_only = False
            return action

        def _row(code, label, log_date):
            row = MagicMock()
            row.operation_action = _action(code, label)
            row.log_date = log_date
            row.created_at = log_date
            row.media_rows = MagicMock(all=MagicMock(return_value=[]))
            row.latitude = ''
            row.longitude = ''
            return row

        logs = [
            _row('OA-0004', 'Confirm Loaded', t_confirm),
            _row('OA-0006', 'Delivery Arrival', t_delivery),
            _row('OA-0003', 'Start Loading', t_load),
        ]
        workflow = build_workflow_status(shipment, logs)
        by_key = {row['step_key']: row for row in workflow}
        self.assertIn('03:01 PM', by_key['loading']['display_timestamp'])
        self.assertIn('03:02 PM', by_key['delivery']['display_timestamp'])

    @patch('mobile_api.history.projections.history_timeline_projection.JobDetailTimelineService')
    def test_closed_cod_workflow_shows_full_milestone_chain(self, mock_timeline_service):
        from datetime import datetime, timezone

        from mobile_api.history.projections.history_detail_projection import (
            build_workflow_status,
        )

        def _action(code, label, **kwargs):
            action = MagicMock()
            action.action_id = code
            action.action_code = code
            action.english_label = label
            action.arabic_label = ''
            action.sequence_number = kwargs.get('sequence_number', 0)
            action.shipment_status_impact = kwargs.get('shipment_status_impact', '')
            action.movement_status_impact = ''
            action.auto_pod_post = kwargs.get('auto_pod_post', False)
            action.hard_copy_collection = kwargs.get('hard_copy_collection', False)
            action.auto_treasury_post = kwargs.get('auto_treasury_post', False)
            action.sequence_category = ''
            action.admin_only = False
            return action

        actions = [
            _action('OA-0002', 'Pickup', sequence_number=2),
            _action('OA-0003', 'Start Loading', sequence_number=3),
            _action('OA-0005', 'In Transit', sequence_number=5),
            _action('OA-0006', 'Delivery Arrival', sequence_number=6, shipment_status_impact='At_Delivery'),
            _action('OA-0007', 'Start Unloading', sequence_number=7),
            _action(
                'OA-0008',
                'POD',
                sequence_number=8,
                auto_pod_post=True,
                hard_copy_collection=True,
                shipment_status_impact='Delivered',
            ),
            _action('OA-0009', 'Collect Payment', sequence_number=9, auto_treasury_post=True),
            _action('OA-0010', 'Job Closed', sequence_number=10, shipment_status_impact='Closed'),
        ]
        service = MagicMock()
        service._workflow_actions.return_value = actions
        service._filter_workflow_actions_for_context.return_value = actions
        mock_timeline_service.return_value = service

        booking = MagicMock()
        booking.order_type = 'COD'
        booking.loading_address = None
        booking.delivery_address = None
        booking.route_display = 'Riyadh → Jeddah'

        shipment = MagicMock()
        shipment.shipment_no = 'SH-0102'
        shipment.shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.order_type = ''
        shipment.collection_status = TenantShipment.CollectionStatus.COLLECTED
        shipment.pod_status = TenantShipment.PodStatus.COMPLETED
        shipment.booking = booking
        shipment.cargo = None
        shipment.loading_address = None
        shipment.delivery_address = None
        shipment.route_display = ''
        shipment.booking_item_type = 'Backload'
        shipment.booking_item_ref = ''
        shipment.pk = uuid4()

        def _log(code, label, when, **kwargs):
            row = MagicMock()
            row.operation_action = _action(code, label, **kwargs)
            row.log_id = uuid4()
            row.log_no = f'L-{code}'
            row.log_date = when
            row.created_at = when
            row.latitude = ''
            row.longitude = ''
            row.media_rows = MagicMock(all=MagicMock(return_value=[]))
            return row

        t0 = datetime(2026, 6, 24, 15, 0, tzinfo=timezone.utc)
        logs = [
            _log('OA-0002', 'Pickup', t0, sequence_number=2),
            _log('OA-0003', 'Start Loading', t0.replace(minute=1), sequence_number=3),
            _log('OA-0005', 'In Transit', t0.replace(minute=2), sequence_number=5),
            _log('OA-0006', 'Delivery Arrival', t0.replace(minute=3), sequence_number=6, shipment_status_impact='At_Delivery'),
            _log('OA-0007', 'Start Unloading', t0.replace(minute=4), sequence_number=7),
            _log(
                'OA-0008',
                'POD',
                t0.replace(minute=5),
                sequence_number=8,
                auto_pod_post=True,
                hard_copy_collection=True,
                shipment_status_impact='Delivered',
            ),
            _log('OA-0009', 'Collect Payment', t0.replace(minute=6), sequence_number=9, auto_treasury_post=True),
            _log('OA-0010', 'Job Closed', t0.replace(minute=7), sequence_number=10, shipment_status_impact='Closed'),
        ]

        workflow = build_workflow_status(shipment, logs)
        keys = [row['step_key'] for row in workflow]
        self.assertEqual(
            keys,
            [
                'pickup',
                'loading',
                'in_transit',
                'delivery',
                'pod',
                'unloading',
                'payment',
                'job_closed',
            ],
        )
        self.assertTrue(all(row['completed'] for row in workflow))
        self.assertTrue(all(row['display_timestamp'] for row in workflow))
