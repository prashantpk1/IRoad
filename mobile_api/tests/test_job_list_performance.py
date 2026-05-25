"""
Tests for job list performance helpers and pagination.
"""
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from mobile_api.helpers.job_list_performance import (
    job_list_page_action_batch_enabled,
    resolve_include_total,
)
from mobile_api.helpers.job_list_pagination import MobileJobListPagination
from mobile_api.helpers.job_list_query import (
    MOVEMENT_JOB_LIST_ONLY,
    SHIPMENT_JOB_LIST_ONLY,
    SHIPMENT_JOB_LIST_RELATED,
)
from mobile_api.helpers.job_list_serialize import serialize_job_card_items


class JobListPerformanceToggleTests(SimpleTestCase):
    def test_include_total_query_override(self):
        factory = RequestFactory()
        request = factory.get('/', {'include_total': '0'})
        request.query_params = request.GET
        self.assertFalse(resolve_include_total(request))

    def test_page_action_batch_default_on(self):
        with patch(
            'mobile_api.helpers.job_list_performance.settings',
            MOBILE_JOB_LIST_PAGE_ACTION_BATCH=True,
        ):
            self.assertTrue(job_list_page_action_batch_enabled())


class JobListQueryShapeTests(SimpleTestCase):
    def test_shipment_related_trimmed(self):
        self.assertNotIn('truck__truck_type', SHIPMENT_JOB_LIST_RELATED)
        self.assertIn('truck', SHIPMENT_JOB_LIST_RELATED)

    def test_only_fields_bounded(self):
        self.assertLess(len(SHIPMENT_JOB_LIST_ONLY), 25)
        self.assertLess(len(MOVEMENT_JOB_LIST_ONLY), 20)


class JobListSerializeTests(SimpleTestCase):
    def test_fast_path_returns_items_unchanged(self):
        items = [{'job_id': '1', 'job_type': 'shipment'}]
        out = serialize_job_card_items(items, use_fast_path=True)
        self.assertIs(out, items)


class JobListPaginationTests(SimpleTestCase):
    def test_page_size_capped(self):
        factory = RequestFactory()
        request = factory.get('/', {'page_size': '500'})
        request.query_params = request.GET
        paginator = MobileJobListPagination()
        with patch(
            'mobile_api.helpers.job_list_guards.job_list_max_page_size',
            return_value=25,
        ):
            self.assertEqual(paginator.get_page_size(request), 25)
