"""
Timeline engine tests — preview, pagination, cursor, ordering, dedupe.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, TestCase

from mobile_api.job_detail.dto.job_detail_context import JobDetailContext
from mobile_api.job_detail.projections.timeline_projection import build_timeline_section
from mobile_api.job_detail.services.job_detail_projection_cache import (
    JobDetailProjectionCache,
)
from mobile_api.job_detail.timeline.timeline_cursor_service import (
    JobDetailTimelineCursorService,
)
from mobile_api.job_detail.timeline.timeline_event_mapper import (
    EVENT_COD,
    EVENT_DELAY,
    EVENT_HARD_POD,
    EVENT_MOVEMENT,
    EVENT_POD,
    classify_event_type,
    dedupe_timeline_events,
    filter_hidden_timeline_events,
    map_action_to_pending_timeline_event,
    map_log_to_timeline_event,
    merge_actions_with_timeline_logs,
    pin_job_close_timeline_last,
    sort_timeline_display_order,
    sort_logs_newest_first,
    timeline_event_is_pod_verified,
)
from tenant_workspace.models import TenantShipment
from mobile_api.job_detail.timeline.timeline_service import JobDetailTimelineService
from iroad_tenants.operation_runtime.timeline_cursor import TimelineCursor


def _driver():
    d = MagicMock()
    d.pk = uuid4()
    return d


def _action(*, code='A1', label='Start', **flags):
    a = MagicMock()
    a.action_code = code
    a.english_label = label
    a.arabic_label = ''
    a.action_id = flags.get('action_id', uuid4())
    a.sequence_number = flags.get('sequence_number', 0)
    a.shipment_status_impact = flags.get('shipment_status_impact', '')
    a.movement_status_impact = flags.get('movement_status_impact', '')
    a.auto_pod_post = flags.get('auto_pod_post', False)
    a.hard_copy_collection = flags.get('hard_copy_collection', False)
    return a


def _log(*, log_id=None, log_date=None, action=None, log_no='L-1'):
    row = MagicMock()
    row.log_id = log_id or uuid4()
    row.pk = row.log_id
    row.log_no = log_no
    row.log_date = log_date or datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)
    row.created_at = row.log_date
    row.operation_action = action
    row.source = 'Manual'
    row.source_channel = 'mobile'
    row.notes = ''
    row.shipment_id = None
    row.truck_movement_id = None
    row.latitude = ''
    row.longitude = ''
    return row


class TimelineEventMapperTests(SimpleTestCase):
    def test_classify_pod_cod_movement_delay(self):
        self.assertEqual(classify_event_type(_action(code='DELAY', label='Traffic delay')), EVENT_DELAY)
        self.assertEqual(
            classify_event_type(_action(code='A9', label='Collect payment COD')),
            EVENT_COD,
        )
        self.assertEqual(
            classify_event_type(_action(code='A7', label='Upload POD', auto_pod_post=True)),
            EVENT_POD,
        )
        self.assertEqual(
            classify_event_type(_action(movement_status_impact='In Progress')),
            EVENT_MOVEMENT,
        )

    def test_dedupe_preserves_first(self):
        events = [
            {'log_id': 'a', 'event_type': 'action'},
            {'log_id': 'a', 'event_type': 'pod'},
            {'log_id': 'b', 'event_type': 'action'},
        ]
        out = dedupe_timeline_events(events)
        self.assertEqual([e['log_id'] for e in out], ['a', 'b'])
        self.assertEqual(out[0]['event_type'], 'action')

    def test_sort_logs_newest_first(self):
        old = _log(log_date=datetime(2026, 5, 1, tzinfo=timezone.utc), log_no='old')
        new = _log(log_date=datetime(2026, 5, 25, tzinfo=timezone.utc), log_no='new')
        ordered = sort_logs_newest_first([old, new])
        self.assertEqual(ordered[0].log_no, 'new')

    def test_filter_hidden_timeline_events_removes_pod_verified(self):
        events = [
            {'action_code': 'OA-0008', 'action_label': 'POD'},
            {
                'action_code': 'A_POD_VERIFY',
                'action_label': 'POD Verified',
                'source_channel': 'auto_cod_verify',
            },
        ]
        filtered = filter_hidden_timeline_events(events)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['action_code'], 'OA-0008')
        self.assertTrue(
            timeline_event_is_pod_verified(
                {'action_label': 'POD Verified'},
            ),
        )

    def test_pin_job_close_timeline_last_after_system_auto(self):
        events = [
            {'action_code': 'OA-0009', 'sequence_number': 9},
            {'action_code': 'OA-0010', 'sequence_number': 10, 'action_label': 'Job Closed'},
            {
                'action_code': 'A_POD_VERIFY',
                'sequence_number': 999,
                'is_system_auto': True,
                'source_channel': 'auto_cod_verify',
            },
        ]
        ordered = sort_timeline_display_order(events)
        self.assertEqual(
            [row['action_code'] for row in ordered],
            ['OA-0009', 'OA-0010'],
        )

    def test_job_close_last_when_detected_by_closed_status_impact(self):
        events = [
            {'action_code': 'OA-0009', 'sequence_number': 9},
            {
                'action_code': 'OA-0010',
                'sequence_number': 10,
                'action_label': 'Close Job',
                'status_impact': 'Closed',
            },
            {
                'action_code': 'A_POD_VERIFY',
                'sequence_number': 75,
                'action_label': 'POD Verified',
                'is_system_auto': True,
            },
        ]
        ordered = sort_timeline_display_order(events)
        self.assertEqual(
            [row['action_code'] for row in ordered],
            ['OA-0009', 'OA-0010'],
        )

    def test_map_log_authority_fields(self):
        event = map_log_to_timeline_event(_log(action=_action()))
        self.assertEqual(event['authority'], 'action_log')
        self.assertTrue(event['append_only'])

    def test_classify_hard_pod_event_type(self):
        self.assertEqual(
            classify_event_type(
                _action(code='A7H', label='Hard POD Collection', hard_copy_collection=True),
            ),
            EVENT_HARD_POD,
        )

    @patch(
        'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
        return_value={
            'required': True,
            'pending': True,
            'action_code': 'A7H',
            'pages': [{'label': 'DN-1', 'page_id': '1'}],
            'submit_endpoint': '/api/v1/mobile/driver/hard-pod/submit/',
            'execute_action_code': 'A7H',
        },
    )
    def test_pending_hard_pod_timeline_includes_navigation(self, _mock_block):
        action = _action(code='A7H', label='Hard POD Collection', hard_copy_collection=True)
        shipment = SimpleNamespace(
            pk=uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=1,
        )
        event = map_action_to_pending_timeline_event(
            action,
            shipment=shipment,
            tenant_schema='tenant_test',
        )
        self.assertEqual(event['screen'], 'pod_capture')
        self.assertEqual(event['capture_mode'], 'hard_copy_confirmation')
        self.assertEqual(event['timeline_state'], 'pending')

    def test_pending_a8_routes_to_execute_not_pod_capture(self):
        action = _action(code='A8', label='Unloading Completed')
        event = map_action_to_pending_timeline_event(action, tenant_schema='tenant_test')
        self.assertEqual(event['screen'], 'job_detail')
        self.assertEqual(event['action'], 'execute_action')
        self.assertNotIn('capture_mode', event)

    def test_pending_oa_0008_hard_pod_routes_digital_first(self):
        action = _action(
            code='OA-0008',
            label='POD',
            auto_pod_post=True,
            hard_copy_collection=True,
            shipment_status_impact='Delivered',
            sequence_number=8,
        )
        shipment = SimpleNamespace(
            pk=uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=1,
        )
        with patch(
            'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
            return_value={
                'required': True,
                'pending': True,
                'applicable': True,
                'execute_action_code': 'OA-0008',
                'pages': [{'page_id': 'p1', 'label': 'DN-1'}],
            },
        ):
            event = map_action_to_pending_timeline_event(
                action,
                shipment=shipment,
                tenant_schema='tenant_test',
            )
        self.assertEqual(event['capture_mode'], 'digital_evidence')
        self.assertTrue(event['hard_pod'])
        self.assertTrue(event['includes_hard_copy'])
        self.assertEqual(
            event['pod_capture_steps'],
            ['digital_evidence', 'hard_copy_confirmation'],
        )

    def test_pending_a7_hard_shipment_includes_pod_capture_steps(self):
        action = _action(code='A7', label='Upload POD', auto_pod_post=True)
        shipment = SimpleNamespace(
            pk=uuid4(),
            pod_type=TenantShipment.PodType.HARD,
            pod_doc_count=2,
        )
        with patch(
            'mobile_api.helpers.action_navigation_metadata.build_hard_copy_confirmation_block',
            return_value={
                'required': True,
                'pending': True,
                'applicable': True,
                'execute_action_code': 'A7',
            },
        ):
            event = map_action_to_pending_timeline_event(
                action,
                shipment=shipment,
                tenant_schema='tenant_test',
            )
        self.assertEqual(event['screen'], 'pod_capture')
        self.assertEqual(
            event['pod_capture_steps'],
            ['digital_evidence', 'hard_copy_confirmation'],
        )
        self.assertTrue(event['includes_hard_copy'])


class TimelineCursorServiceTests(SimpleTestCase):
    def test_encode_decode_roundtrip(self):
        svc = JobDetailTimelineCursorService()
        log = _log()
        token = svc.encode_next_cursor(log)
        self.assertTrue(token)
        parsed = svc.parse_cursor_token(token)
        self.assertIsInstance(parsed, TimelineCursor)
        self.assertEqual(parsed.log_id, str(log.log_id))

    def test_invalid_cursor_rejected(self):
        svc = JobDetailTimelineCursorService()
        self.assertFalse(svc.validate_cursor_token('not-a-valid-cursor'))


class TimelineServiceTests(SimpleTestCase):
    def test_preview_reuses_cache_without_query(self):
        logs = [
            _log(log_no='n1', action=_action(code='A1')),
            _log(log_no='n2', action=_action(code='A2')),
            _log(log_no='n3', action=_action(code='A3')),
        ]
        cache = JobDetailProjectionCache(shipment_logs=logs)
        shipment = MagicMock()
        shipment.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
            projection_cache=cache,
        )

        with patch(
            'iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page',
        ) as mock_fetch:
            bundle = JobDetailTimelineService().build_preview_bundle(ctx, preview_limit=2)
            mock_fetch.assert_not_called()

        self.assertEqual(len(bundle['timeline_preview']), 2)
        self.assertTrue(bundle['has_more'])
        self.assertTrue(bundle['timeline_cursor'])

    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_shipment_pagination_has_more(self, mock_fetch):
        rows = [_log(log_no=f'n{i}') for i in range(3)]
        mock_fetch.return_value = rows

        shipment = MagicMock()
        shipment.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment.pk),
            shipment=shipment,
        )

        page = JobDetailTimelineService().fetch_page_for_context(ctx, limit=2)
        self.assertEqual(len(page.timeline_preview), 2)
        self.assertTrue(page.has_more)
        self.assertTrue(page.timeline_cursor)
        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args.kwargs['limit'], 3)

    @patch('iroad_tenants.services.timeline_service.TimelineService.fetch_scoped_timeline_page')
    def test_movement_timeline_scope(self, mock_fetch):
        mock_fetch.return_value = [_log(action=_action(movement_status_impact='In Progress'))]
        movement = MagicMock()
        movement.pk = uuid4()
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='movement',
            job_id=str(movement.pk),
            movement=movement,
        )
        page = JobDetailTimelineService().fetch_page_for_context(ctx, limit=10)
        self.assertEqual(len(page.timeline_preview), 1)
        self.assertEqual(page.timeline_preview[0]['event_type'], EVENT_MOVEMENT)
        self.assertIs(mock_fetch.call_args.kwargs['movement'], movement)
        self.assertIsNone(mock_fetch.call_args.kwargs['shipment'])

    def test_filter_workflow_actions_for_movement_and_shipment_contexts(self):
        act_a1 = _action(code='A1', label='Start Job')
        act_a1.sequence_category = 'job'

        act_a2 = _action(code='A2', label='Pickup Arrival')
        act_a2.sequence_category = 'job'

        act_em1 = _action(code='EM1', label='Start Movement')
        act_em1.sequence_category = 'empty_move'

        act_em2 = _action(code='EM2', label='Depart Empty')
        act_em2.sequence_category = 'empty_move'

        actions = [act_a1, act_a2, act_em1, act_em2]
        svc = JobDetailTimelineService()

        # Case 1: Movement job
        movement = MagicMock()
        ctx_movement = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='movement',
            job_id=str(uuid4()),
            movement=movement,
        )
        filtered_movement = svc._filter_workflow_actions_for_context(actions, context=ctx_movement)
        self.assertEqual(
            [a.action_code for a in filtered_movement],
            ['EM1', 'EM2'],
        )

        # Case 2: Shipment job
        shipment = MagicMock()
        shipment.order_type = 'COD'
        ctx_shipment = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(uuid4()),
            shipment=shipment,
        )
        filtered_shipment = svc._filter_workflow_actions_for_context(actions, context=ctx_shipment)
        self.assertEqual(
            [a.action_code for a in filtered_shipment],
            ['A2'],
        )

        # Case 3: Booking job (Auto Shipment before first leg) — job actions only, no empty move
        booking = MagicMock()
        booking.order_type = 'COD'
        ctx_booking = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='booking',
            job_id=str(uuid4()),
            booking=booking,
        )
        filtered_booking = svc._filter_workflow_actions_for_context(actions, context=ctx_booking)
        self.assertEqual(
            [a.action_code for a in filtered_booking],
            ['A1', 'A2'],
        )

    def test_booking_job_uses_full_shipment_timeline(self):
        act_a1 = _action(code='A1', label='Start Job')
        act_a2 = _action(code='A2', label='Pickup Arrival')
        act_a3 = _action(code='A3', label='Start Loading')
        act_a4 = _action(code='A4', label='Confirm Loaded')
        act_a5 = _action(code='A5', label='Depart In Transit')
        act_a6 = _action(code='A6', label='Delivery Arrival')
        act_a7 = _action(code='A7', label='Upload POD')
        act_a8 = _action(code='A8', label='Unloading Completed')
        actions = [act_a1, act_a2, act_a3, act_a4, act_a5, act_a6, act_a7, act_a8]

        booking = MagicMock()
        booking.order_type = 'COD'
        ctx_booking = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='booking',
            job_id=str(uuid4()),
            booking=booking,
        )
        filtered = JobDetailTimelineService()._filter_workflow_actions_for_context(
            actions,
            context=ctx_booking,
        )
        self.assertEqual(
            [a.action_code for a in filtered],
            ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8'],
        )

    def test_backload_bootstrap_booking_uses_full_shipment_timeline(self):
        act_a1 = _action(code='A1', label='Start Job')
        act_a2 = _action(code='A2', label='Pickup Arrival')
        act_a3 = _action(code='A3', label='Start Loading')
        act_a4 = _action(code='A4', label='Confirm Loaded')
        act_a5 = _action(code='A5', label='Depart In Transit')
        act_a6 = _action(code='A6', label='Delivery Arrival')
        act_a7 = _action(code='A7', label='Upload POD')
        actions = [act_a1, act_a2, act_a3, act_a4, act_a5, act_a6, act_a7]

        booking = MagicMock()
        booking.order_type = 'Standard'
        ctx_booking = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='booking',
            job_id=str(uuid4()),
            booking=booking,
        )
        svc = JobDetailTimelineService()
        with patch(
            'mobile_api.job_detail.timeline.timeline_service.resolve_booking_job_execution_context',
            return_value={
                'backload_bootstrap': True,
                'booking_item_type': 'Backload',
            },
        ):
            filtered = svc._filter_workflow_actions_for_context(
                actions,
                context=ctx_booking,
            )
        self.assertEqual(
            [a.action_code for a in filtered],
            ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7'],
        )

    def test_merge_keeps_booking_preshipment_logs_on_shipment_timeline(self):
        """A2/A3 logged on booking before A4 must stay performed on shipment job."""
        booking_id = uuid4()
        act_a2 = _action(code='A2', label='Pickup Arrival')
        act_a2.action_id = uuid4()
        act_a3 = _action(code='A3', label='Start Loading')
        act_a3.action_id = uuid4()
        act_a4 = _action(code='A4', label='Confirm Loaded')
        act_a4.action_id = uuid4()

        log_a2 = _log(
            log_no='L-A2',
            action=act_a2,
            log_date=datetime(2026, 6, 17, 18, 0, tzinfo=timezone.utc),
        )
        log_a2.shipment_id = None
        log_a2.booking_id = booking_id

        log_a3 = _log(
            log_no='L-A3',
            action=act_a3,
            log_date=datetime(2026, 6, 17, 18, 5, tzinfo=timezone.utc),
        )
        log_a3.shipment_id = None
        log_a3.booking_id = booking_id

        shipment_id = uuid4()
        log_a4 = _log(
            log_no='L-A4',
            action=act_a4,
            log_date=datetime(2026, 6, 17, 20, 9, tzinfo=timezone.utc),
        )
        log_a4.shipment_id = shipment_id

        shipment = SimpleNamespace(pk=shipment_id, booking_id=booking_id)
        events = merge_actions_with_timeline_logs(
            [act_a2, act_a3, act_a4],
            [log_a4, log_a3, log_a2],
            shipment=shipment,
        )
        by_code = {event['action_code']: event for event in events}
        self.assertTrue(by_code['A2']['is_performed'])
        self.assertTrue(by_code['A3']['is_performed'])
        self.assertTrue(by_code['A4']['is_performed'])
        self.assertEqual(by_code['A2']['log_no'], 'L-A2')
        self.assertEqual(by_code['A3']['log_no'], 'L-A3')

    def test_pickup_loading_not_implicit_when_later_step_performed(self):
        """Confirm Loaded without A2/A3 logs must not auto-complete pickup/loading."""
        act_a2 = _action(code='OA-0002', label='Pickup Arrival', sequence_number=2)
        act_a3 = _action(code='OA-0003', label='Start Loading', sequence_number=3)
        act_a4 = _action(code='OA-0004', label='Confirm Loaded', sequence_number=4)
        log_a4 = _log(
            log_no='L-A4',
            action=act_a4,
            log_date=datetime(2026, 6, 23, 13, 0, tzinfo=timezone.utc),
        )
        events = merge_actions_with_timeline_logs(
            [act_a2, act_a3, act_a4],
            [log_a4],
        )
        by_code = {event['action_code']: event for event in events}
        self.assertFalse(by_code['OA-0002']['is_performed'])
        self.assertFalse(by_code['OA-0003']['is_performed'])
        self.assertTrue(by_code['OA-0004']['is_performed'])

    def test_unloading_true_pod_false_after_delivery_arrival(self):
        """After delivery arrival: unloading green, POD still pending."""
        act_a6 = _action(
            code='OA-0006',
            label='Delivery Arrival',
            sequence_number=6,
            shipment_status_impact='At_Delivery',
        )
        act_a7 = _action(code='OA-0007', label='Start Unloading', sequence_number=7)
        act_a8 = _action(
            code='OA-0008',
            label='POD',
            auto_pod_post=True,
            hard_copy_collection=True,
            shipment_status_impact='Delivered',
            sequence_number=8,
        )
        log_a6 = _log(
            log_no='L-A6',
            action=act_a6,
            log_date=datetime(2026, 6, 23, 12, 56, tzinfo=timezone.utc),
        )
        events = merge_actions_with_timeline_logs(
            [act_a6, act_a7, act_a8],
            [log_a6],
        )
        by_code = {event['action_code']: event for event in events}
        self.assertFalse(by_code['OA-0007']['is_performed'])
        self.assertFalse(by_code['OA-0007'].get('implicit_performed'))
        self.assertFalse(by_code['OA-0008']['is_performed'])

    def test_unloading_stays_pending_when_only_pod_performed(self):
        act_a7 = _action(code='OA-0007', label='Start Unloading', sequence_number=7)
        act_a8 = _action(
            code='OA-0008',
            label='POD',
            auto_pod_post=True,
            shipment_status_impact='Delivered',
            sequence_number=8,
        )

        log_a8 = _log(
            log_no='L-POD',
            action=act_a8,
            log_date=datetime(2026, 6, 23, 12, 57, tzinfo=timezone.utc),
        )

        events = merge_actions_with_timeline_logs(
            [act_a7, act_a8],
            [log_a8],
        )
        by_code = {event['action_code']: event for event in events}
        self.assertTrue(by_code['OA-0008']['is_performed'])
        self.assertFalse(by_code['OA-0007']['is_performed'])
        self.assertFalse(by_code['OA-0007'].get('implicit_performed'))

    def test_filter_always_hides_hard_pod_from_timeline(self):
        act_a7 = _action(code='A7', label='Upload POD')
        act_a7h = _action(code='A7H', label='Hard POD Collection')
        act_a7h.hard_copy_collection = True
        shipment = MagicMock()
        shipment.order_type = 'COD'
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(uuid4()),
            shipment=shipment,
        )
        filtered = JobDetailTimelineService()._filter_workflow_actions_for_context(
            [act_a7, act_a7h],
            context=ctx,
        )
        self.assertEqual([a.action_code for a in filtered], ['A7'])

    def test_filter_keeps_combined_pod_with_hard_copy_on_timeline(self):
        act_pod = _action(
            code='OA-0008',
            label='POD',
            auto_pod_post=True,
            hard_copy_collection=True,
        )
        act_a7h = _action(code='A7H', label='Hard POD Collection')
        act_a7h.hard_copy_collection = True
        shipment = MagicMock()
        shipment.order_type = 'COD'
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='t',
            user_id='u',
            job_type='shipment',
            job_id=str(uuid4()),
            shipment=shipment,
        )
        filtered = JobDetailTimelineService()._filter_workflow_actions_for_context(
            [act_pod, act_a7h],
            context=ctx,
        )
        self.assertEqual([a.action_code for a in filtered], ['OA-0008'])

    def test_cod_close_timeline_order_collect_payment_pod_verify_job_closed(self):
        act_cod = _action(
            code='OA-0009',
            label='Collect Payment',
            sequence_number=9,
        )
        act_close = _action(
            code='OA-0010',
            label='Job Closed',
            sequence_number=10,
            shipment_status_impact='Closed',
        )
        act_verify = _action(
            code='A_POD_VERIFY',
            label='POD Verified',
            sequence_number=75,
            shipment_status_impact='Delivered',
        )
        shipment_id = uuid4()
        log_cod = _log(
            log_no='L-9',
            action=act_cod,
            log_date=datetime(2026, 6, 24, 12, 19, 0, tzinfo=timezone.utc),
        )
        log_close = _log(
            log_no='L-10',
            action=act_close,
            log_date=datetime(2026, 6, 24, 12, 20, 0, tzinfo=timezone.utc),
        )
        log_verify = _log(
            log_no='L-PV',
            action=act_verify,
            log_date=datetime(2026, 6, 24, 12, 19, 30, tzinfo=timezone.utc),
        )
        log_verify.source_channel = 'auto_cod_verify'
        log_verify.source = 'System'
        for row in (log_cod, log_close, log_verify):
            row.shipment_id = shipment_id

        shipment = MagicMock()
        shipment.pk = shipment_id
        shipment.order_type = 'COD'
        ctx = JobDetailContext(
            driver=_driver(),
            tenant_schema='tenant_a',
            user_id='u1',
            job_type='shipment',
            job_id=str(shipment_id),
            shipment=shipment,
        )
        svc = JobDetailTimelineService()
        with patch.object(svc, '_workflow_actions', return_value=[act_cod, act_close]):
            events = svc._workflow_events_for_context(
                ctx,
                logs=[log_cod, log_close, log_verify],
                request=None,
            )
        self.assertEqual(
            [row['action_code'] for row in events],
            ['OA-0009', 'OA-0010'],
        )


class TimelineProjectionTests(TestCase):
    @patch(
        'mobile_api.job_detail.projections.job_detail_projection_builder.build_issue_timeline_events',
        return_value=[],
    )
    @patch.object(JobDetailTimelineService, 'build_preview_bundle')
    def test_projection_contract_keys(self, mock_preview, _mock_issue_timeline):
        mock_preview.return_value = {
            'scope': 'shipment',
            'preview_limit': 20,
            'timeline_preview': [{'log_id': '1'}],
            'timeline_cursor': 'tok',
            'has_more': True,
        }
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
        section = build_timeline_section(ctx)
        self.assertIn('timeline_preview', section)
        self.assertIn('timeline_cursor', section)
        self.assertTrue(section['has_more'])
