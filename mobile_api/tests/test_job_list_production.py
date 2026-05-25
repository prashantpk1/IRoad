"""
Production hardening tests for driver job list module.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from mobile_api.helpers.job_list_cache import (
    build_list_fingerprint,
    summary_cache_key,
)
from mobile_api.helpers.job_list_guards import (
    sanitize_search_term,
    validate_pagination_request,
)
from mobile_api.helpers.job_list_observability import (
    estimate_payload_bytes,
    filters_fingerprint,
)
from mobile_api.helpers.job_list_pagination import MobileJobListPagination
from mobile_api.throttling import MobileJobListThrottle


class JobListGuardsTests(SimpleTestCase):
    @override_settings(MOBILE_API_JOBS_MAX_PAGE=10, MOBILE_API_JOBS_MAX_OFFSET_ROWS=100)
    def test_validate_pagination_rejects_deep_offset(self):
        err = validate_pagination_request(page=11, page_size=10)
        self.assertIsNotNone(err)

    def test_sanitize_search_truncates(self):
        term = 'x' * 100
        self.assertEqual(len(sanitize_search_term(term)), 64)


class JobListCacheTests(SimpleTestCase):
    def test_summary_cache_key_stable(self):
        key = summary_cache_key(tenant_schema='tenant_a', driver_id='42')
        self.assertIn('summary', key)
        self.assertIn('tenant_a', key)

    def test_fingerprint_changes_with_page(self):
        class F:
            tab = 'active'
            queue = 'none'
            search = ''
            date_from = None
            date_to = None
            date_field = 'updated'

        a = build_list_fingerprint(
            entity_type='shipment',
            filters=F(),
            sort='updated_desc',
            page=1,
            page_size=10,
            include_actions=True,
            include_total=False,
        )
        b = build_list_fingerprint(
            entity_type='shipment',
            filters=F(),
            sort='updated_desc',
            page=2,
            page_size=10,
            include_actions=True,
            include_total=False,
        )
        self.assertNotEqual(a, b)


class JobListObservabilityTests(SimpleTestCase):
    def test_estimate_payload_bytes(self):
        self.assertGreater(estimate_payload_bytes([{'id': 1}]), 0)

    def test_filters_fingerprint_deterministic(self):
        a = filters_fingerprint(
            entity_type='shipment',
            tab='active',
            queue='none',
            search='',
            sort='updated_desc',
            date_from='',
            date_to='',
            date_field='updated',
            page=1,
            page_size=20,
            include_actions=True,
            include_total=False,
        )
        b = filters_fingerprint(
            entity_type='shipment',
            tab='active',
            queue='none',
            search='',
            sort='updated_desc',
            date_from='',
            date_to='',
            date_field='updated',
            page=1,
            page_size=20,
            include_actions=True,
            include_total=False,
        )
        self.assertEqual(a, b)


class JobListPaginationTests(SimpleTestCase):
    @override_settings(MOBILE_JOB_LIST_INCLUDE_TOTAL_DEFAULT=False)
    def test_include_total_default_off(self):
        request = MagicMock()
        request.query_params = {}
        from mobile_api.helpers.job_list_performance import resolve_include_total

        self.assertFalse(resolve_include_total(request))

    @override_settings(MOBILE_API_JOBS_MAX_PAGE_SIZE=25)
    def test_page_size_capped(self):
        request = MagicMock()
        request.query_params = {'page_size': '200'}
        paginator = MobileJobListPagination()
        self.assertEqual(paginator.get_page_size(request), 25)


class JobListThrottleTests(SimpleTestCase):
    def test_mobile_jobs_scope(self):
        self.assertEqual(MobileJobListThrottle.scope, 'mobile_jobs')


class JobListDriverScopeTests(SimpleTestCase):
    @override_settings(MOBILE_API_JOBS_UNION_DRIVER_SCOPE=True)
    def test_union_scope_query_uses_subquery(self):
        from unittest.mock import MagicMock

        from mobile_api.helpers.job_list_driver_scope import (
            driver_shipment_pk_union_subquery,
        )

        driver = MagicMock()
        driver.pk = '11111111-1111-4111-8111-111111111111'
        driver.driver_id = driver.pk
        subq = driver_shipment_pk_union_subquery(driver)
        sql = str(subq.query).lower()
        self.assertIn('union', sql)
