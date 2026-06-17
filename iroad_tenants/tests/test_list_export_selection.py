from django.http import QueryDict
from django.test import SimpleTestCase

from iroad_tenants.list_table_utils import (
    EXPORT_SELECTED_PARAM,
    apply_list_export_selection,
    parse_export_selected_values,
)


class _FakeQuerySet:
    def __init__(self, filters=None):
        self.filters = filters or {}

    def filter(self, **kwargs):
        merged = dict(self.filters)
        merged.update(kwargs)
        return _FakeQuerySet(merged)


class _FakeRequest:
    def __init__(self, query_string=''):
        self.GET = QueryDict(query_string)


class ListExportSelectionTests(SimpleTestCase):
    def test_parse_export_selected_values_empty(self):
        request = _FakeRequest()
        self.assertEqual(parse_export_selected_values(request), [])

    def test_parse_export_selected_values_splits_csv(self):
        request = _FakeRequest(f'{EXPORT_SELECTED_PARAM}=ADDR-1,ADDR-2')
        self.assertEqual(parse_export_selected_values(request), ['ADDR-1', 'ADDR-2'])

    def test_apply_list_export_selection_noop_without_selection(self):
        request = _FakeRequest()
        qs = _FakeQuerySet()
        result = apply_list_export_selection(qs, request, 'address_code')
        self.assertIs(result, qs)
        self.assertEqual(result.filters, {})

    def test_apply_list_export_selection_filters_when_selected(self):
        request = _FakeRequest(f'{EXPORT_SELECTED_PARAM}=ADDR-1,ADDR-2')
        qs = _FakeQuerySet()
        result = apply_list_export_selection(qs, request, 'address_code')
        self.assertEqual(result.filters, {'address_code__in': ['ADDR-1', 'ADDR-2']})
