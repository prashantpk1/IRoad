"""
Replay short-circuit tests — kernel must not run on idempotent replay.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TransactionTestCase

from mobile_api.execution.dto.execute_action_result import ExecuteActionResult
from mobile_api.execution.guards.execution_idempotency_guard import IdempotencyKeys
from mobile_api.execution.services.execute_action_orchestrator import (
    ExecuteActionOrchestrator,
)


@contextmanager
def _fake_schema(_name):
    yield


def _driver():
    return SimpleNamespace(pk='drv-1', driver_id='drv-1', driver_name='D')


def _existing_log():
    return SimpleNamespace(
        log_id='log-existing',
        log_no='OAL-99',
        log_date=None,
        operation_action=SimpleNamespace(action_code='A2'),
    )


class ExecutionReplaySafetyTests(TransactionTestCase):
    @patch('mobile_api.execution.services.execute_action_orchestrator.schema_context', _fake_schema)
    def test_replay_skips_kernel_and_evidence(self):
        orch = ExecuteActionOrchestrator()
        orch._reconcile_service.prepare_pre_execute = MagicMock()
        orch._idempotency_guard.normalize_request_keys = MagicMock(
            return_value=IdempotencyKeys(idempotency_key='key-1', source_ref='ref'),
        )
        orch._idempotency_guard.detect_idempotent_replay = MagicMock(return_value=True)
        orch._validation_service.validate_pre_execute_after_idempotency = MagicMock()
        orch._evidence_service.validate_required_evidence = MagicMock()
        orch._execute_kernel = MagicMock()
        orch._media_service.persist_execution_media = MagicMock()
        orch._response_service.build_execute_result = MagicMock(
            return_value=ExecuteActionResult(payload={'execution': {'replayed': True}}, http_status=200),
        )

        result = orch.execute_driver_action(
            driver=_driver(),
            tenant=SimpleNamespace(schema_name='tenant_test'),
            job_type='shipment',
            job_id='ship-1',
            action_code='A2',
            payload={
                'client_action_id': 'key-1',
                'content_hash': 'h',
                'workflow_version': 'w',
            },
        )

        self.assertEqual(result.http_status, 200)
        orch._execute_kernel.assert_not_called()
        orch._evidence_service.validate_required_evidence.assert_not_called()
        orch._validation_service.validate_pre_execute_after_idempotency.assert_not_called()
        orch._media_service.persist_execution_media.assert_not_called()
