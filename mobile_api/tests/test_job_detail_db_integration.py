"""
PostgreSQL-backed E2E tests — Job Detail reads, timeline, indexes, allowed actions.

Runs automatically when PostgreSQL is available and at least one tenant schema
is Job Detail READY (migrations 0093–0095 + indexes).

Force enable: MOBILE_API_RUN_JOB_DETAIL_DB_TESTS=1
Disable: MOBILE_API_SKIP_JOB_DETAIL_DB_TESTS=1
Schema: MOBILE_API_JOB_DETAIL_TEST_SCHEMA=<tenant_schema>
"""
from __future__ import annotations

import uuid
from unittest import skipUnless

from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from mobile_api.tests.job_detail_db_support import (
    JobDetailDbTestBase,
    job_detail_db_tests_enabled,
    skip_reason,
)


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailReadDbTests(JobDetailDbTestBase):
    def test_timeline_scoped_queryset_bounded(self):
        from mobile_api.helpers.job_detail_guards import job_detail_timeline_max_items
        from iroad_tenants.services.timeline_service import TimelineService

        qs = TimelineService.scoped_action_log_queryset(
            shipment=self.shipment,
            driver_id=self.driver.pk,
        )
        rows = list(qs[: job_detail_timeline_max_items() + 1])
        self.assertLessEqual(len(rows), job_detail_timeline_max_items() + 1)

    def test_detail_log_batch_low_query_count(self):
        from mobile_api.helpers.job_detail_perf import load_scoped_action_logs

        with CaptureQueriesContext(connection) as ctx:
            rows = load_scoped_action_logs(
                shipment=self.shipment,
                driver_id=self.driver.pk,
                limit=15,
            )
        self.assertGreaterEqual(len(rows), 0)
        self.assertLessEqual(len(ctx), 2)

    def test_allowed_actions_real_workflow_engine(self):
        from mobile_api.services.driver_job_allowed_actions_service import (
            DriverJobAllowedActionsService,
        )

        out = DriverJobAllowedActionsService.get_shipment_allowed_actions(
            driver=self.driver,
            shipment_id=str(self.shipment.shipment_id),
        )
        self.assertTrue(out.get('success'))
        block = out.get('allowed_actions') or {}
        self.assertIn('actions', block)
        self.assertIsInstance(block['actions'], list)

    def test_timeline_cursor_pagination_no_duplicates(self):
        from mobile_api.services.driver_job_timeline_service import (
            DriverJobTimelineService,
        )

        if not self.actions:
            self.skipTest('No active operation actions')
        self.create_action_logs(count=5)

        request = self.make_timeline_request(page_size='2')
        page1 = DriverJobTimelineService.get_shipment_timeline(
            driver=self.driver,
            shipment_id=str(self.shipment.shipment_id),
            request=request,
        )
        self.assertTrue(page1.get('success'))
        tl1 = page1['timeline']
        self.assertEqual(tl1['pagination']['mode'], 'cursor')
        self.assertEqual(len(tl1['items']), 2)
        ids_page1 = [item['log_id'] for item in tl1['items']]

        if not tl1['pagination'].get('has_next'):
            self.skipTest('Need >2 logs for cursor page test')

        request2 = self.make_timeline_request(
            cursor=tl1['pagination']['next_cursor'],
            page_size='2',
        )
        page2 = DriverJobTimelineService.get_shipment_timeline(
            driver=self.driver,
            shipment_id=str(self.shipment.shipment_id),
            request=request2,
        )
        self.assertTrue(page2.get('success'))
        ids_page2 = [item['log_id'] for item in page2['timeline']['items']]
        self.assertFalse(set(ids_page1) & set(ids_page2))

    def test_timeline_invalid_cursor_rejected(self):
        from mobile_api.services.driver_job_timeline_service import (
            DriverJobTimelineService,
        )

        request = self.make_timeline_request(cursor='not-a-valid-cursor!!!')
        out = DriverJobTimelineService.get_shipment_timeline(
            driver=self.driver,
            shipment_id=str(self.shipment.shipment_id),
            request=request,
        )
        self.assertFalse(out.get('success'))
        self.assertEqual(out.get('code'), 'invalid_cursor')

    def test_movement_timeline_db_scope(self):
        from mobile_api.services.driver_job_timeline_service import (
            DriverJobTimelineService,
        )

        if not self.actions:
            self.skipTest('No active operation actions')
        self.create_action_logs(count=2, movement=self.movement, clear_shipment=True)

        mv_request = self.factory.get(
            f'/api/v1/mobile/driver/jobs/movements/{self.movement.movement_id}/timeline/',
            {'page_size': '10'},
        )
        mv_request.query_params = mv_request.GET
        out = DriverJobTimelineService.get_movement_timeline(
            driver=self.driver,
            movement_id=str(self.movement.movement_id),
            request=mv_request,
        )
        self.assertTrue(out.get('success'))
        self.assertGreaterEqual(len(out['timeline']['items']), 1)

    def test_idempotency_unique_constraint_db(self):
        from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
        from tenant_workspace.models import TenantOperationActionLog

        if not self.actions:
            self.skipTest('No active actions')
        key = f'jd-test-{uuid.uuid4().hex}'
        action = self.actions[0]
        log1 = TenantOperationActionLog.objects.create(
            log_no=f'JD-{uuid.uuid4().hex[:8]}',
            log_sequence=1,
            log_date=timezone.now(),
            operation_action=action,
            shipment=self.shipment,
            driver=self.driver,
            idempotency_key=key,
            source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TenantOperationActionLog.objects.create(
                    log_no=f'JD-{uuid.uuid4().hex[:8]}',
                    log_sequence=2,
                    log_date=timezone.now(),
                    operation_action=action,
                    shipment=self.shipment,
                    driver=self.driver,
                    idempotency_key=key,
                    source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                )
        log1.delete()

    def test_timeline_indexes_present(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname IN (
                    'tenant_oal_ship_drv_dt_id_idx',
                    'tenant_oal_move_drv_dt_id_idx'
                  )
                """
            )
            names = {row[0] for row in cursor.fetchall()}
        self.assertIn('tenant_oal_ship_drv_dt_id_idx', names)
        self.assertIn('tenant_oal_move_drv_dt_id_idx', names)
