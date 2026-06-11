from datetime import datetime, timezone
from unittest.mock import Mock

from django.core.paginator import Paginator
from django.test import RequestFactory, SimpleTestCase

from iroad_tenants.views import (
    LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
    _apply_audit_sl_no_column_filter,
    _apply_audit_table_search_and_column_filters,
    _assign_audit_event_sl_numbers,
    _audit_event_matches_table_search,
    _audit_list_query_params,
    _audit_page_row_sl_no,
    _critical_account_audit_order_by,
    _prepare_audit_events_for_pagination,
    _sl_no_matches_filter,
)


class AuditTableFilterTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _event(self, **kwargs):
        defaults = {
            'timestamp': datetime(2026, 6, 11, 5, 10, tzinfo=timezone.utc),
            'action': 'Login Success',
            'module': 'Authentication',
            'performed_by': 'French and Hopkins Associates',
        }
        defaults.update(kwargs)
        return defaults

    def test_table_search_matches_action_module_and_performed_by(self):
        event = self._event()
        self.assertTrue(
            _audit_event_matches_table_search(
                event,
                'login success',
                LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
            )
        )
        self.assertTrue(
            _audit_event_matches_table_search(
                event,
                'authentication',
                LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
            )
        )
        self.assertTrue(
            _audit_event_matches_table_search(
                event,
                'french',
                LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
            )
        )
        self.assertFalse(
            _audit_event_matches_table_search(
                event,
                'missing-user',
                LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
            )
        )

    def test_apply_table_search_and_column_filters(self):
        events = [
            self._event(action='Session Active', performed_by='Alice'),
            self._event(action='Login Success', performed_by='Bob'),
        ]
        request = self.factory.get('/audit/login-session-events/', {'q': 'bob'})
        filtered, search_q, active = _apply_audit_table_search_and_column_filters(
            events,
            request,
            global_search_columns=LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
        )
        self.assertEqual(search_q, 'bob')
        self.assertTrue(active)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['performed_by'], 'Bob')

    def test_apply_column_filter_on_action(self):
        events = [
            self._event(action='Session Active'),
            self._event(action='Login Success'),
        ]
        request = self.factory.get('/audit/login-session-events/', {'filter_3': 'active'})
        filtered, _, active = _apply_audit_table_search_and_column_filters(
            events,
            request,
            global_search_columns=LOGIN_SESSION_EVENTS_GLOBAL_SEARCH_COLUMNS,
        )
        self.assertTrue(active)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['action'], 'Session Active')

    def test_apply_sl_no_filter_after_sort(self):
        events = [
            self._event(performed_by='First'),
            self._event(performed_by='Second'),
            self._event(performed_by='Third'),
        ]
        _assign_audit_event_sl_numbers(events)
        request = self.factory.get('/audit/login-session-events/', {'filter_1': '2'})
        filtered = _apply_audit_sl_no_column_filter(events, request)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['performed_by'], 'Second')
        self.assertEqual(filtered[0]['sl_no'], 2)

    def test_sl_no_filter_uses_exact_match_for_numeric_values(self):
        self.assertTrue(_sl_no_matches_filter(2, '2'))
        self.assertFalse(_sl_no_matches_filter(12, '2'))
        self.assertTrue(_sl_no_matches_filter(12, '12'))

    def test_assign_sl_numbers_renumbers_filtered_list(self):
        events = [
            self._event(performed_by='Alice'),
            self._event(performed_by='Bob'),
        ]
        _assign_audit_event_sl_numbers(events)
        self.assertEqual(events[0]['sl_no'], 1)
        self.assertEqual(events[1]['sl_no'], 2)

    def test_prepare_audit_events_filters_by_sl_no(self):
        events = [
            self._event(performed_by='First'),
            self._event(performed_by='Second'),
            self._event(performed_by='Third'),
        ]
        request = self.factory.get('/audit/login-session-events/', {'filter_1': '2'})
        prepared = _prepare_audit_events_for_pagination(
            events,
            request,
            sort_col=1,
            sort_dir='asc',
        )
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]['performed_by'], 'Second')

    def test_audit_page_row_sl_no_descending_on_first_page(self):
        page_obj = Mock(start_index=Mock(return_value=1), end_index=Mock(return_value=10))
        self.assertEqual(
            _audit_page_row_sl_no(page_obj, 0, sort_col=1, sort_dir='desc'),
            10,
        )
        self.assertEqual(
            _audit_page_row_sl_no(page_obj, 9, sort_col=1, sort_dir='desc'),
            1,
        )

    def test_timestamp_sort_ascending_changes_row_order(self):
        events = [
            self._event(
                performed_by='Newest',
                timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
            ),
            self._event(
                performed_by='Oldest',
                timestamp=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
            ),
        ]
        request = self.factory.get('/audit/login-session-events/')
        prepared = _prepare_audit_events_for_pagination(
            events,
            request,
            sort_col=2,
            sort_dir='asc',
        )
        self.assertEqual(prepared[0]['performed_by'], 'Oldest')
        self.assertEqual(prepared[1]['performed_by'], 'Newest')

    def test_sl_no_sort_descending_reverses_page_display_numbers(self):
        events = [
            self._event(
                performed_by='First',
                timestamp=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
            ),
            self._event(
                performed_by='Second',
                timestamp=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
            ),
        ]
        request = self.factory.get('/audit/login-session-events/')
        prepared = _prepare_audit_events_for_pagination(
            events,
            request,
            sort_col=1,
            sort_dir='desc',
        )
        page_obj = Paginator(prepared, 10).get_page(1)
        sl_numbers = [
            _audit_page_row_sl_no(page_obj, index, sort_col=1, sort_dir='desc')
            for index in range(len(page_obj.object_list))
        ]
        self.assertEqual(sl_numbers, [2, 1])
        self.assertEqual(prepared[0]['performed_by'], 'Second')

    def test_critical_account_sl_sort_keeps_default_timestamp_order(self):
        self.assertEqual(_critical_account_audit_order_by(1, 'desc'), ('-timestamp',))
        self.assertEqual(_critical_account_audit_order_by(1, 'asc'), ('-timestamp',))

    def test_audit_list_query_params_preserves_table_search_and_filters(self):
        request = self.factory.get(
            '/audit/login-session-events/',
            {
                'date_from': '2026-06-01',
                'q': 'french',
                'filter_4': 'auth',
                'sort_col': '2',
                'sort_dir': 'desc',
                'page': '2',
            },
        )
        params = _audit_list_query_params(request)
        self.assertEqual(params['date_from'], '2026-06-01')
        self.assertEqual(params['q'], 'french')
        self.assertEqual(params['filter_4'], 'auth')
        self.assertEqual(params['sort_col'], '2')
        self.assertEqual(params['sort_dir'], 'desc')
        self.assertNotIn('page', params)
