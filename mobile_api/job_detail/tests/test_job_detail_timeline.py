"""
Timeline engine tests — preview, pagination, cursor, ordering, dedupe.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    EVENT_MOVEMENT,
    EVENT_POD,
    classify_event_type,
    dedupe_timeline_events,
    map_log_to_timeline_event,
    sort_logs_newest_first,
)
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

    def test_map_log_authority_fields(self):
        event = map_log_to_timeline_event(_log(action=_action()))
        self.assertEqual(event['authority'], 'action_log')
        self.assertTrue(event['append_only'])


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
