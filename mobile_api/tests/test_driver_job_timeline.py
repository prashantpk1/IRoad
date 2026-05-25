"""
Job detail timeline API tests — cursor, projections, view wiring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from mobile_api.helpers.timeline_cursor import (
    TimelineCursor,
    apply_timeline_cursor_filter,
    encode_cursor_from_log,
    parse_timeline_cursor_param,
)
from mobile_api.helpers.timeline_projections import project_timeline_item
from mobile_api.serializers.driver_job_timeline import JobTimelineResponseDataSerializer


class ShipmentTimelineQueryShapeTests(SimpleTestCase):
    def test_scoped_shipment_uses_union_not_movement_join(self):
        from iroad_tenants.services.timeline_service import TimelineService

        shipment_id = uuid4()
        driver_id = uuid4()
        shipment = MagicMock()
        shipment.pk = shipment_id

        qs = TimelineService.scoped_action_log_queryset(
            shipment=shipment,
            driver_id=driver_id,
        )
        sql = str(qs.query).lower()
        self.assertIn('union', sql)
        self.assertNotIn('truck_movement__shipment', sql)

    def test_scoped_movement_uses_single_fk_filter(self):
        from iroad_tenants.services.timeline_service import TimelineService

        movement = MagicMock()
        movement.pk = uuid4()

        qs = TimelineService.scoped_action_log_queryset(
            movement=movement,
            driver_id=uuid4(),
        )
        sql = str(qs.query).lower()
        self.assertIn('truck_movement_id', sql)
        self.assertNotIn('union', sql)

    def test_shipment_scope_q_avoids_movement_join(self):
        from iroad_tenants.services.timeline_query import shipment_action_log_scope_q
        from tenant_workspace.models import TenantOperationActionLog

        shipment_pk = uuid4()
        qs = TenantOperationActionLog.objects.filter(
            shipment_action_log_scope_q(shipment_pk),
        )
        sql = str(qs.query).lower()
        self.assertNotIn('truck_movement__shipment', sql)
        self.assertIn('truck_movement_id', sql)


class TimelineCursorTests(SimpleTestCase):
    def test_encode_and_parse_roundtrip(self):
        log = MagicMock()
        log.log_id = uuid4()
        log.log_date = datetime(2026, 5, 21, 10, 0, 0, tzinfo=timezone.utc)
        token = encode_cursor_from_log(log)
        self.assertTrue(token)

        request = MagicMock()
        request.query_params = {'cursor': token}
        parsed = parse_timeline_cursor_param(request)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.log_id, str(log.log_id))

    def test_invalid_cursor_token(self):
        request = MagicMock()
        request.query_params = {'cursor': 'not-valid!!!'}
        self.assertIsNone(parse_timeline_cursor_param(request))


class TimelineProjectionTests(SimpleTestCase):
    def test_project_item_includes_gps_and_events(self):
        action = MagicMock()
        action.action_code = 'A9'
        action.english_label = 'Collect Payment'
        action.arabic_label = ''
        action.shipment_status_impact = ''
        action.movement_status_impact = ''
        action.booking_status_impact = ''
        action.auto_pod_post = False
        action.auto_movement_post = False

        log = MagicMock()
        log.log_id = uuid4()
        log.log_no = 'OAL-1'
        log.log_date = datetime(2026, 5, 21, 12, 0, 0, tzinfo=timezone.utc)
        log.operation_action = action
        log.created_by_label = 'Driver One'
        log.driver = None
        log.latitude = '24.7'
        log.longitude = '46.6'
        log.map_link = 'https://maps.example/?q=24.7,46.6'
        log.notes = 'Paid'
        log.source = 'Mobile'
        log.source_channel = 'mobile_driver'
        log.shipment_id = uuid4()
        log.truck_movement_id = None

        item = project_timeline_item(
            log,
            media_previews=[{'media_id': str(uuid4()), 'line_no': 1, 'media_type': 'photo', 'description': '', 'captured_at': None, 'preview_url': None, 'has_file': False}],
        )
        self.assertEqual(item['action_name'], 'Collect Payment')
        self.assertTrue(item['events']['is_cod'])
        self.assertEqual(item['gps']['latitude'], '24.7')
        self.assertEqual(item['media_count'], 1)


class TimelineSerializerTests(SimpleTestCase):
    def test_response_schema(self):
        job_id = uuid4()
        log_id = uuid4()
        data = {
            'timeline': {
                'job_type': 'shipment',
                'job_id': str(job_id),
                'job_no': 'SH-1',
                'items': [
                    {
                        'log_id': str(log_id),
                        'log_no': 'OAL-1',
                        'action_name': 'Depart',
                        'action_code': 'A5',
                        'execution_time': '2026-05-21T10:00:00+00:00',
                        'driver_name': 'Driver',
                        'gps': {'latitude': '', 'longitude': '', 'map_link': ''},
                        'notes': '',
                        'media_previews': [],
                        'media_count': 0,
                        'status_impacts': {
                            'shipment': 'In Transit',
                            'movement': None,
                            'booking': None,
                        },
                        'events': {
                            'is_pod': False,
                            'is_cod': False,
                            'is_reversal': False,
                            'is_status_impact': True,
                        },
                    }
                ],
                'pagination': {
                    'mode': 'cursor',
                    'page_size': 20,
                    'count': 1,
                    'has_next': False,
                    'next_cursor': None,
                },
            }
        }
        ser = JobTimelineResponseDataSerializer(data=data)
        self.assertTrue(ser.is_valid(), ser.errors)


class TimelineViewTests(SimpleTestCase):
    def test_shipment_timeline_success(self):
        from rest_framework.test import APIRequestFactory
        from mobile_api.views.driver_job_timeline import DriverShipmentTimelineView

        shipment_id = uuid4()
        factory = APIRequestFactory()
        request = factory.get(
            '/api/v1/mobile/driver/jobs/shipments/%s/timeline/' % shipment_id,
            {'page_size': '10'},
        )
        request.auth = {
            'tenant_schema': 'tenant_a',
            'driver_id': str(uuid4()),
            'sub': str(uuid4()),
        }

        timeline_payload = {
            'job_type': 'shipment',
            'job_id': str(shipment_id),
            'job_no': 'SH-1',
            'items': [],
            'pagination': {
                'mode': 'cursor',
                'page_size': 10,
                'count': 0,
                'has_next': False,
                'next_cursor': None,
            },
        }

        view = DriverShipmentTimelineView.as_view()
        with patch(
            'mobile_api.permissions.HasDriverJobsAccess.has_permission',
            return_value=True,
        ):
            with patch(
                'mobile_api.permissions.IsMobileAuthenticated.has_permission',
                return_value=True,
            ):
                with patch(
                    'mobile_api.views.driver_job_detail.resolve_secure_job_list_context',
                    return_value={
                        'success': True,
                        'ctx': MagicMock(driver=MagicMock(pk=uuid4())),
                    },
                ):
                    with patch(
                        'mobile_api.views.driver_job_timeline.DriverJobTimelineService.get_shipment_timeline',
                        return_value={'success': True, 'timeline': timeline_payload},
                    ):
                        response = view(request, shipment_id=shipment_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['timeline']['pagination']['mode'], 'cursor')
