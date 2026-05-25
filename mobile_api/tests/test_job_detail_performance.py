"""
Job detail performance helpers — batching, caps, guards.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from mobile_api.helpers.job_detail_guards import (
    job_detail_log_scan_limit,
    job_detail_timeline_max_items,
    validate_timeline_page_size,
)
from mobile_api.helpers.job_detail_perf import (
    build_timeline_preview_items,
    latest_log_from_rows,
    resolve_log_fetch_limit,
)
from mobile_api.helpers.job_detail_observability import classify_job_detail_operation


class JobDetailPerfTests(SimpleTestCase):
    def test_resolve_log_fetch_limit_uses_max_of_preview_and_scan(self):
        with override_settings(
            MOBILE_JOB_DETAIL_TIMELINE_PREVIEW_LIMIT=15,
            MOBILE_JOB_DETAIL_LOG_SCAN_LIMIT=120,
        ):
            lim = resolve_log_fetch_limit(
                include_timeline_preview=True,
                include_execution_state=True,
            )
        self.assertEqual(lim, 120)

    def test_latest_log_from_rows_picks_first(self):
        a, b = MagicMock(), MagicMock()
        self.assertIs(latest_log_from_rows([a, b]), a)
        self.assertIsNone(latest_log_from_rows([]))

    def test_build_timeline_preview_batches_media(self):
        log_id = uuid4()
        row = MagicMock()
        row.log_id = log_id
        with patch(
            'mobile_api.helpers.job_detail_perf.batch_media_previews_by_log',
            return_value={str(log_id): [{'media_id': str(uuid4())}]},
        ) as mock_media:
            with patch(
                'mobile_api.helpers.job_detail_perf.project_timeline_item',
                return_value={'log_id': str(log_id)},
            ):
                items = build_timeline_preview_items([row], preview_limit=1)
        mock_media.assert_called_once()
        self.assertEqual(len(items), 1)

    def test_timeline_page_size_clamped(self):
        with override_settings(MOBILE_JOB_TIMELINE_MAX_PAGE_SIZE=50):
            self.assertEqual(validate_timeline_page_size(999), 50)

    def test_classify_execute_path(self):
        self.assertEqual(
            classify_job_detail_operation(
                '/api/v1/mobile/driver/jobs/shipments/x/actions/execute/',
                'POST',
            ),
            'execute_action',
        )


class ReconcilePrefetchTests(SimpleTestCase):
    def test_reconcile_accepts_prefetched_logs(self):
        from iroad_tenants.operation_runtime.workflow_state_reconciler import (
            reconcile_shipment_execution_state,
        )

        shipment = MagicMock()
        shipment.shipment_status = 'In Transit'
        shipment.pk = uuid4()
        log = MagicMock()
        log.operation_action = MagicMock()
        log.operation_action.shipment_status_impact = 'In Transit'
        log.operation_action.movement_status_impact = ''
        log.operation_action.action_code = 'A5'
        log.log_date = None
        log.created_at = None

        with patch(
            'iroad_tenants.operation_runtime.workflow_state_reconciler.scoped_shipment_action_logs',
        ) as mock_scoped:
            with patch(
                'iroad_tenants.operation_runtime.workflow_state_reconciler.derive_shipment_status_from_logs',
                return_value={
                    'authoritative_status': 'In Transit',
                    'latest_impact_status': 'In Transit',
                    'peak_impact_status': 'In Transit',
                    'log_count': 1,
                    'reversal_log_count': 0,
                },
            ):
                with patch(
                    'iroad_tenants.operation_runtime.workflow_state_reconciler.derive_job_execution_stage',
                    return_value={'execution_sub_stage': '', 'operational_stage': 'In Transit'},
                ):
                    with patch(
                        'iroad_tenants.operation_runtime.workflow_state_reconciler.derive_latest_action_status',
                        return_value='In Transit',
                    ):
                        with patch(
                            'iroad_tenants.operation_runtime.workflow_state_reconciler.aggregate_latest_action_log',
                            return_value=None,
                        ):
                            out = reconcile_shipment_execution_state(
                                shipment,
                                prefetched_logs=[log],
                            )
        mock_scoped.assert_not_called()
        self.assertEqual(out.get('entity_type'), 'shipment')
