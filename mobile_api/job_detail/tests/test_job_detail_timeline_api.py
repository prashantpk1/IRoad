"""
Tests for GET /api/v1/mobile/driver/jobs/<job_type>/<job_id>/timeline/
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIRequestFactory, force_authenticate

from mobile_api.authentication import MobileUser
from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.exceptions import JobDetailError
from mobile_api.job_detail.services.job_detail_timeline_api_service import (
    JobDetailTimelineApiService,
)
from mobile_api.job_detail.timeline.timeline_cursor_service import (
    JobDetailTimelineCursorService,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    dedupe_timeline_events,
    sort_logs_newest_first,
)
from mobile_api.job_detail.timeline.timeline_service import JobDetailTimelineService
from mobile_api.job_detail.views.job_detail_timeline_view import (
    JobDetailTimelineAPIView,
)
from tenant_workspace.models import DriverMaster


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
    d.driver_status = DriverMaster.Status.ACTIVE
    return d


def _log(*, log_id=None, log_date=None, log_no='L-1'):
    row = MagicMock()
    row.log_id = log_id or uuid4()
    row.pk = row.log_id
    row.log_no = log_no
    row.log_date = log_date or datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    row.created_at = row.log_date
    row.operation_action = MagicMock(
        action_code='A1',
        english_label='Start',
        arabic_label='',
        shipment_status_impact='',
        movement_status_impact='',
        auto_pod_post=False,
        hard_copy_collection=False,
    )
    row.source = 'Manual'
    row.source_channel = 'mobile'
    row.notes = ''
    row.shipment_id = None
    row.truck_movement_id = None
    row.latitude = ''
    row.longitude = ''
    return row


class TimelineApiPaginationTests(SimpleTestCase):
    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_first_page_bounded_has_more(self, mock_fetch):
        rows = [_log(log_no=f'n{i}') for i in range(4)]
        mock_fetch.return_value = rows

        shipment = MagicMock()
        shipment.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )

        payload = JobDetailTimelineService().fetch_timeline_api_page(ctx, limit=3)
        self.assertEqual(len(payload['events']), 3)
        self.assertTrue(payload['has_more'])
        self.assertTrue(payload['next_cursor'])
        self.assertEqual(mock_fetch.call_args.kwargs['limit'], 4)

    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_cursor_continuation_passes_parsed_cursor(self, mock_fetch):
        cursor_svc = JobDetailTimelineCursorService()
        page1_logs = [_log(log_no='new'), _log(log_no='mid')]
        token = cursor_svc.encode_next_cursor(page1_logs[-1])

        shipment = MagicMock()
        shipment.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )

        mock_fetch.return_value = [_log(log_no='old')]
        JobDetailTimelineService().fetch_timeline_api_page(
            ctx,
            cursor=token,
            limit=10,
        )

        self.assertIsNotNone(mock_fetch.call_args.kwargs['cursor'])
        self.assertEqual(
            mock_fetch.call_args.kwargs['cursor'].log_id,
            str(page1_logs[-1].log_id),
        )

    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_last_page_has_no_cursor(self, mock_fetch):
        mock_fetch.return_value = [_log()]
        shipment = MagicMock()
        shipment.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )
        payload = JobDetailTimelineService().fetch_timeline_api_page(ctx, limit=5)
        self.assertFalse(payload['has_more'])
        self.assertEqual(payload['next_cursor'], '')


class TimelineApiOrderingDedupeTests(SimpleTestCase):
    def test_ordering_newest_first_stable(self):
        logs = [
            _log(
                log_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
                log_no='old',
            ),
            _log(
                log_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
                log_no='new',
            ),
        ]
        ordered = sort_logs_newest_first(logs)
        self.assertEqual(ordered[0].log_no, 'new')
        self.assertEqual(ordered[1].log_no, 'old')

    def test_duplicate_log_ids_removed(self):
        events = dedupe_timeline_events(
            [
                {'log_id': 'same', 'event_type': 'action'},
                {'log_id': 'same', 'event_type': 'pod'},
                {'log_id': 'other', 'event_type': 'action'},
            ]
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['log_id'], 'same')


class TimelineApiScopeTests(SimpleTestCase):
    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_shipment_timeline_scope(self, mock_fetch):
        mock_fetch.return_value = [_log()]
        shipment = MagicMock()
        shipment.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )
        payload = JobDetailTimelineService().fetch_timeline_api_page(ctx)
        self.assertEqual(len(payload['events']), 1)
        self.assertEqual(payload['events'][0]['authority'], 'action_log')
        self.assertIs(mock_fetch.call_args.kwargs['shipment'], shipment)

    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_movement_timeline_scope(self, mock_fetch):
        mock_fetch.return_value = [_log()]
        movement = MagicMock()
        movement.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='movement',
            job_id=str(movement.pk),
            movement=movement,
        )
        JobDetailTimelineService().fetch_timeline_api_page(ctx)
        self.assertIs(mock_fetch.call_args.kwargs['movement'], movement)
        self.assertIsNone(mock_fetch.call_args.kwargs['shipment'])


class TimelineApiIntegrationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.url = reverse(
            'mobile_api:driver_job_detail_timeline',
            kwargs={'job_type': 'shipment', 'job_id': str(uuid4())},
        )

    @patch(
        'mobile_api.job_detail.views.job_detail_timeline_view.JobDetailTimelineApiService',
    )
    @patch(
        'mobile_api.job_detail.views.job_detail_timeline_view.resolve_job_detail_driver',
    )
    def test_get_timeline_success_contract(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        mock_svc_cls.return_value.fetch_timeline_page.return_value = {
            'events': [{'log_id': '1', 'event_type': 'action', 'authority': 'action_log'}],
            'next_cursor': 'cursor-token',
            'has_more': True,
        }

        request = self.factory.get(self.url, {'limit': '10'})
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = JobDetailTimelineAPIView.as_view()(
            request,
            job_type='shipment',
            job_id='ship-1',
        )

        self.assertEqual(response.status_code, 200)
        data = response.data['data']
        self.assertIn('events', data)
        self.assertIn('next_cursor', data)
        self.assertTrue(data['has_more'])

    @patch(
        'mobile_api.job_detail.views.job_detail_timeline_view.JobDetailTimelineApiService',
    )
    @patch(
        'mobile_api.job_detail.views.job_detail_timeline_view.resolve_job_detail_driver',
    )
    def test_invalid_cursor_returns_400(self, mock_resolve, mock_svc_cls):
        driver = _driver()
        mock_resolve.return_value = (driver, None, None)
        mock_svc_cls.return_value.fetch_timeline_page.side_effect = JobDetailError(
            'Invalid timeline cursor',
            code='invalid_timeline_cursor',
            http_status=400,
        )

        request = self.factory.get(self.url, {'cursor': 'bad'})
        force_authenticate(
            request,
            user=MobileUser(_jwt_payload(driver_id=driver.driver_id)),
            token=_jwt_payload(driver_id=driver.driver_id),
        )
        response = JobDetailTimelineAPIView.as_view()(
            request,
            job_type='shipment',
            job_id='ship-1',
        )
        self.assertEqual(response.status_code, 400)

    @patch(
        'mobile_api.job_detail.services.job_detail_timeline_api_service.schema_context',
    )
    @patch(
        'mobile_api.job_detail.services.job_detail_timeline_api_service.ShipmentJobResolver',
    )
    def test_timeline_service_does_not_load_projection_cache(
        self, mock_resolver_cls, mock_schema
    ):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)

        shipment = MagicMock()
        shipment.pk = uuid4()
        from mobile_api.job_detail.services.shipment_job_resolver import (
            ShipmentJobResolveResult,
        )

        mock_resolver_cls.return_value.resolve.return_value = ShipmentJobResolveResult(
            shipment=shipment,
            booking=None,
        )

        with patch.object(
            JobDetailTimelineService,
            'fetch_timeline_api_page',
            return_value={'events': [], 'next_cursor': '', 'has_more': False},
        ) as mock_fetch, patch(
            'mobile_api.job_detail.services.job_detail_projection_service.load_projection_cache',
        ) as mock_cache, patch(
            'mobile_api.job_detail.services.job_detail_projection_service.reconcile_job_detail_entities',
        ) as mock_reconcile:
            JobDetailTimelineApiService().fetch_timeline_page(
                _driver(),
                'shipment',
                str(shipment.pk),
                tenant_schema='tenant_a',
            )
            mock_fetch.assert_called_once()
            mock_cache.assert_not_called()
            mock_reconcile.assert_not_called()
