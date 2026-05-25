"""
Tests for job list filter, search, date, ordering, and filter service pipeline.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase

from mobile_api.helpers.job_list_dates import (
    parse_job_list_date_range,
    parse_date_field_param,
)
from mobile_api.helpers.job_list_filter_service import build_driver_job_list_queryset
from mobile_api.helpers.job_list_filters import (
    JobListFilters,
    apply_job_filters,
    parse_shipment_job_list_filters,
)
from mobile_api.helpers.job_list_ordering import apply_job_ordering, parse_job_sort
from mobile_api.helpers.job_list_search import (
    is_searchable,
    movement_job_search_q,
    shipment_job_search_q,
)
from mobile_api.helpers.operational_status import driver_shipment_scope_q


class JobListSearchTests(SimpleTestCase):
    def test_short_search_ignored(self):
        self.assertFalse(is_searchable('a'))
        self.assertTrue(is_searchable('SH'))

    def test_shipment_search_uses_indexed_lookup_not_icontains(self):
        q = shipment_job_search_q('SH-100')
        sql = str(q).lower()
        self.assertIn('shipment_no', sql)
        self.assertTrue('iexact' in sql or 'istartswith' in sql)
        self.assertNotIn('icontains', sql)

    def test_movement_search_uses_exists_for_shipment_link(self):
        driver = MagicMock()
        driver.pk = uuid4()
        q = movement_job_search_q('SH-200', driver=driver)
        sql = str(q).lower()
        self.assertIn('movement_no', sql)
        self.assertIn('exists', sql)
        self.assertNotIn('icontains', sql)


class JobListDateTests(SimpleTestCase):
    def test_inverted_range_swapped(self):
        r = parse_job_list_date_range(
            date_from='2026-05-20',
            date_to='2026-05-01',
        )
        self.assertEqual(r.date_from, date(2026, 5, 1))
        self.assertEqual(r.date_to, date(2026, 5, 20))

    def test_date_field_param(self):
        factory = RequestFactory()
        request = factory.get('/', {'date_field': 'operational'})
        request.query_params = request.GET
        self.assertEqual(parse_date_field_param(request), 'operational')


class JobListFilterParseTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _req(self, path, params):
        request = self.factory.get(path, params)
        request.query_params = request.GET
        return request

    def test_all_required_tabs_parse(self):
        for tab in ('active', 'completed', 'cancelled', 'all'):
            f = parse_shipment_job_list_filters(
                self._req('/shipments/', {'tab': tab}),
            )
            self.assertEqual(f.tab, tab)

    def test_pod_and_cod_queues(self):
        f = parse_shipment_job_list_filters(
            self._req('/shipments/', {}),
            locked_tab='active',
            locked_queue='pod_pending',
        )
        self.assertEqual(f.queue, 'pod_pending')

        f2 = parse_shipment_job_list_filters(
            self._req('/shipments/', {}),
            locked_queue='cod_pending',
        )
        self.assertEqual(f2.queue, 'cod_pending')

    def test_empty_move_queue(self):
        from mobile_api.helpers.job_list_filters import parse_movement_job_list_filters

        f = parse_movement_job_list_filters(
            self._req('/movements/', {}),
            locked_queue='empty_move',
        )
        self.assertEqual(f.queue, 'empty_move')


class JobListOrderingTests(SimpleTestCase):
    def test_priority_sort_parses(self):
        factory = RequestFactory()
        request = factory.get('/', {'sort': 'priority_desc'})
        request.query_params = request.GET
        self.assertEqual(parse_job_sort(request), 'priority_desc')

    def test_shipment_priority_ordering_annotates(self):
        from tenant_workspace.models import TenantShipment

        qs = TenantShipment.objects.all()
        ordered = apply_job_ordering(qs, entity_type='shipment', sort='priority_desc')
        self.assertIn('mobile_operational_rank', str(ordered.query))


class JobListFilterServiceTests(SimpleTestCase):
    def test_pipeline_builds_query(self):
        from tenant_workspace.models import TenantShipment

        driver = MagicMock()
        driver.pk = uuid4()
        driver.driver_id = driver.pk
        filters = JobListFilters(tab='active', search='SH-1')
        qs = build_driver_job_list_queryset(
            driver=driver,
            entity_type='shipment',
            filters=filters,
            sort='updated_desc',
        )
        self.assertIsNotNone(qs.query)

    def test_cancelled_tab_filter(self):
        from tenant_workspace.models import TenantShipment

        driver = MagicMock()
        driver.pk = uuid4()
        qs = TenantShipment.objects.filter(driver_shipment_scope_q(driver))
        filtered = apply_job_filters(
            qs,
            entity_type='shipment',
            filters=JobListFilters(tab='cancelled'),
        )
        self.assertIn('Cancelled', str(filtered.query))
