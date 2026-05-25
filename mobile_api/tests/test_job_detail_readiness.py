"""Job Detail readiness helper tests."""
from __future__ import annotations

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from mobile_api.helpers.job_detail_readiness import (
    JOB_DETAIL_REQUIRED_INDEXES,
    JobDetailSchemaReport,
    audit_job_detail_schema,
    run_middleware_smoke,
)
from mobile_api.helpers.middleware_request_sim import (
    build_minimal_legacy_fake_request,
    ensure_request_observability_attrs,
    validate_metrics_readiness_on_request,
)


class JobDetailReadinessTests(SimpleTestCase):
    def test_required_indexes_include_timeline_and_execution(self):
        self.assertIn('tenant_oal_ship_drv_dt_id_idx', JOB_DETAIL_REQUIRED_INDEXES)
        self.assertIn('tenant_oal_move_drv_date_idx', JOB_DETAIL_REQUIRED_INDEXES)

    def test_report_ready_when_all_ok(self):
        report = JobDetailSchemaReport(schema='t_test')
        report.migration_ok['tenant_workspace.0093'] = True
        report.timeline_index_ok['tenant_oal_ship_drv_dt_id_idx'] = True
        report.execution_index_ok['tenant_oal_ship_drv_date_idx'] = True
        self.assertTrue(report.ready)

    def test_audit_schema_calls_index_exists(self):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, (1,), (1,)]  # migrations table + checks
        # migration_applied and index_exists will be called - patch
        from unittest.mock import patch

        with patch(
            'mobile_api.helpers.job_detail_readiness.migration_applied',
            return_value=True,
        ), patch(
            'mobile_api.helpers.job_detail_readiness.index_exists',
            return_value=True,
        ):
            report = audit_job_detail_schema(cursor, 't_x')
        self.assertTrue(report.ready)

    def test_middleware_smoke_passes(self):
        ok, err = run_middleware_smoke()
        self.assertTrue(ok, err)

    def test_legacy_fake_request_gets_method(self):
        fake = build_minimal_legacy_fake_request(
            '/api/v1/mobile/driver/jobs/shipments/x/timeline/',
        )
        self.assertEqual(fake.method, 'GET')
        self.assertTrue(fake.path.startswith('/api/v1/mobile/'))

    def test_metrics_readiness_on_legacy_fake(self):
        fake = build_minimal_legacy_fake_request(
            '/api/v1/mobile/driver/jobs/shipments/x/actions/execute/',
        )
        ok, err = validate_metrics_readiness_on_request(fake)
        self.assertTrue(ok, err)

    def test_ensure_attrs_on_bare_object(self):
        class Bare:
            path = '/api/v1/mobile/driver/jobs/movements/x/timeline/'

        req = ensure_request_observability_attrs(Bare())
        self.assertEqual(req.method, 'GET')
        self.assertTrue(hasattr(req, 'headers'))
