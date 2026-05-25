"""
Tests for shipment job list filters and path-locked tabs.
"""
from unittest.mock import MagicMock

from django.test import RequestFactory, SimpleTestCase

from mobile_api.helpers.job_list_filters import (
    JobListFilters,
    parse_shipment_job_list_filters,
)


class ShipmentJobListFilterParseTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _with_query_params(request):
        """DRF-style ``query_params`` for filter parsers."""
        request.query_params = request.GET
        return request

    def test_locked_tab_overrides_query_param(self):
        request = self._with_query_params(self.factory.get(
            '/api/v1/mobile/driver/jobs/shipments/active/',
            {'tab': 'cancelled', 'queue': 'cod_pending'},
        ))
        filters = parse_shipment_job_list_filters(
            request,
            locked_tab='active',
            locked_queue='pod_pending',
        )
        self.assertEqual(filters.tab, 'active')
        self.assertEqual(filters.queue, 'pod_pending')

    def test_general_list_uses_query_tab(self):
        request = self._with_query_params(self.factory.get(
            '/api/v1/mobile/driver/jobs/shipments/',
            {'tab': 'completed', 'q': 'SH-100'},
        ))
        filters = parse_shipment_job_list_filters(request)
        self.assertEqual(filters.tab, 'completed')
        self.assertEqual(filters.search, 'SH-100')
        self.assertEqual(filters.queue, 'none')

    def test_search_accepts_search_alias(self):
        request = self._with_query_params(self.factory.get(
            '/api/v1/mobile/driver/jobs/shipments/',
            {'search': 'BOOK-9'},
        ))
        filters = parse_shipment_job_list_filters(request)
        self.assertEqual(filters.search, 'BOOK-9')
