"""
PostgreSQL-backed integration tests for driver job list (real tenant schema).

Set MOBILE_API_RUN_JOB_LIST_DB_TESTS=1 and ensure migrations 0088–0090 are applied
on MOBILE_API_JOB_LIST_TEST_SCHEMA (or first ready tenant schema).
"""
from __future__ import annotations

import os
import uuid
from datetime import timedelta
from unittest import skipUnless

from django.conf import settings
from django.db import connection
from django.test import RequestFactory, TransactionTestCase, override_settings
from django.utils import timezone

RUN_DB = os.environ.get('MOBILE_API_RUN_JOB_LIST_DB_TESTS', '').strip() in (
    '1',
    'true',
    'yes',
)
PG = connection.vendor == 'postgresql'


def _pick_test_schema() -> str | None:
    explicit = (os.environ.get('MOBILE_API_JOB_LIST_TEST_SCHEMA') or '').strip()
    if explicit:
        return explicit
    from mobile_api.helpers.job_list_readiness import audit_all_schemas, list_tenant_schemas

    for schema in list_tenant_schemas():
        reports = audit_all_schemas(schemas=[schema])
        if reports and reports[0].ready:
            return schema
    names = list_tenant_schemas()
    return names[0] if names else None


@skipUnless(RUN_DB and PG, 'Set MOBILE_API_RUN_JOB_LIST_DB_TESTS=1 and use PostgreSQL')
class JobListDatabaseIntegrationTests(TransactionTestCase):
    """Real ORM + cursor pagination on a tenant schema."""

    databases = {'default'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_schema = _pick_test_schema()
        if not cls.tenant_schema:
            raise cls.skipTest('No tenant schema available')

    def setUp(self):
        from django_tenants.utils import schema_context

        self.factory = RequestFactory()
        self.schema_context = schema_context
        self.ctx = schema_context(self.tenant_schema)
        self.ctx.__enter__()
        self._ensure_driver_and_shipments()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _ensure_driver_and_shipments(self):
        from tenant_workspace.models import DriverMaster, TenantShipment

        self.driver = DriverMaster.objects.filter(
            driver_status=DriverMaster.Status.ACTIVE,
        ).first()
        if self.driver is None:
            code = f'TST{uuid.uuid4().hex[:8]}'
            self.driver = DriverMaster.objects.create(
                driver_code=code,
                driver_status=DriverMaster.Status.ACTIVE,
                driver_source=DriverMaster.DriverSource.IN_SOURCE,
                driver_type=DriverMaster.DriverType.COMPANY,
            )
        now = timezone.now()
        self.shipment_ids: list = []
        for i in range(5):
            sid = uuid.uuid4()
            TenantShipment.objects.create(
                shipment_id=sid,
                shipment_no=f'TST-JL-{uuid.uuid4().hex[:8]}',
                shipment_status=TenantShipment.ShipmentStatus.LOADED,
                sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
                driver=self.driver,
                updated_at=now - timedelta(minutes=i),
                mobile_operational_rank=2,
            )
            self.shipment_ids.append(sid)

    def test_union_driver_scope_returns_assigned_rows(self):
        from mobile_api.helpers.job_list_driver_scope import filter_shipments_for_driver

        ids = set(
            filter_shipments_for_driver(self.driver).filter(
                shipment_id__in=self.shipment_ids,
            ).values_list('pk', flat=True),
        )
        self.assertEqual(ids, set(self.shipment_ids))

    def test_cursor_pagination_no_duplicate_ids(self):
        from mobile_api.helpers.job_list_filter_service import build_driver_job_list_queryset
        from mobile_api.helpers.job_list_filters import JobListFilters
        from mobile_api.helpers.job_list_pagination import MobileJobListPagination

        request = self.factory.get(
            '/api/v1/mobile/driver/jobs/shipments/active/',
            {'page_size': '2'},
        )
        request.query_params = request.GET
        qs = build_driver_job_list_queryset(
            driver=self.driver,
            entity_type='shipment',
            filters=JobListFilters(tab='active'),
            sort='updated_desc',
            include_actions=False,
        )
        paginator = MobileJobListPagination()
        all_ids: list = []
        for _ in range(10):
            page = paginator.paginate_queryset(qs, request, view=None)
            if not page:
                break
            all_ids.extend(
                getattr(r, 'shipment_id', r.pk) for r in page
            )
            if not paginator.next_cursor:
                break
            request = self.factory.get(
                '/api/v1/mobile/driver/jobs/shipments/active/',
                {
                    'page_size': '2',
                    'cursor': paginator.next_cursor,
                },
            )
            request.query_params = request.GET
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_list_query_count_ceiling(self):
        from django.test.utils import CaptureQueriesContext

        from mobile_api.helpers.job_list_filter_service import build_driver_job_list_queryset
        from mobile_api.helpers.job_list_filters import JobListFilters
        from mobile_api.helpers.job_list_pagination import MobileJobListPagination

        request = self.factory.get(
            '/api/v1/mobile/driver/jobs/shipments/active/',
            {'page_size': '5', 'include_actions': '0', 'include_total': '0'},
        )
        request.query_params = request.GET
        qs = build_driver_job_list_queryset(
            driver=self.driver,
            entity_type='shipment',
            filters=JobListFilters(tab='active'),
            sort='updated_desc',
            include_actions=False,
        )
        paginator = MobileJobListPagination()
        with CaptureQueriesContext(connection) as ctx:
            page = paginator.paginate_queryset(qs, request, view=None)
            list(page)
        self.assertLessEqual(len(ctx), 4)

    @override_settings(MOBILE_API_JOBS_ALLOW_OFFSET_PAGINATION=False)
    def test_offset_rejected_in_production_mode(self):
        from mobile_api.helpers.job_list_guards import reject_offset_pagination

        request = self.factory.get('/', {'page': '2'})
        request.query_params = request.GET
        self.assertIsNotNone(reject_offset_pagination(request))

    @override_settings(MOBILE_API_JOBS_STRICT_PAYLOAD=True, MOBILE_API_JOBS_MAX_RESPONSE_BYTES=80)
    def test_strict_payload_rejects_oversize(self):
        from mobile_api.helpers.job_list_guards import enforce_payload_limit

        big = [{'payload': 'x' * 500} for _ in range(10)]
        out, err, code = enforce_payload_limit(big)
        self.assertIsNone(out)
        self.assertEqual(code, 'job_list_payload_too_large')

    def test_priority_desc_uses_operational_rank_field(self):
        from mobile_api.helpers.job_list_ordering import apply_job_ordering

        from mobile_api.helpers.job_list_driver_scope import filter_shipments_for_driver

        qs = filter_shipments_for_driver(self.driver)
        ordered = apply_job_ordering(qs, entity_type='shipment', sort='priority_desc')
        sql = str(ordered.query).lower()
        self.assertIn('mobile_operational_rank', sql)
