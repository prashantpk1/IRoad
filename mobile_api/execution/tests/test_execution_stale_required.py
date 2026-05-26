"""
Stale sync metadata requirement tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.guards.stale_execution_guard import StaleExecutionGuard


class StaleRequiredSyncTests(SimpleTestCase):
    @patch('mobile_api.execution.guards.stale_execution_guard.mobile_execution_require_sync_metadata', return_value=True)
    def test_missing_content_hash_rejected(self, _mock_setting):
        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='d1'),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='s1',
            action_code='A2',
            payload={'workflow_version': 'wf-1'},
            sync_metadata={'content_hash': 'server', 'workflow_version': 'wf-1'},
        )
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_workflow')

    @patch('mobile_api.execution.guards.stale_execution_guard.mobile_execution_require_sync_metadata', return_value=True)
    def test_replay_skips_required_sync(self, _mock_setting):
        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='d1'),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='s1',
            action_code='A2',
            payload={},
            idempotent_replay=True,
        )
        StaleExecutionGuard().assert_not_stale(ctx)
