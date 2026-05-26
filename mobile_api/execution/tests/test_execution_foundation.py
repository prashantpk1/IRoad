"""
Foundation tests — module wiring and response contract shape only (no DB).
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execute_action_response_builder import (
    ExecuteActionResponseBuilder,
)
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.services.execute_action_orchestrator import (
    ExecuteActionOrchestrator,
)


class ExecuteActionFoundationTests(SimpleTestCase):
    def test_response_contract_keys(self):
        context = ExecuteActionContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='shipment',
            job_id='ship-1',
            action_code='A1',
        )
        payload = ExecuteActionResponseBuilder().build(context)
        self.assertEqual(
            set(payload.keys()),
            {
                'execution',
                'workflow',
                'pod_cod',
                'timeline_preview',
                'sync_metadata',
                'alerts',
            },
        )

    def test_movement_omits_pod_cod_in_builder(self):
        context = ExecuteActionContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='movement',
            job_id='mov-1',
            action_code='M1',
            pod_cod={'pod_pending': True},
            timeline={'timeline_preview': [{'id': '1'}]},
        )
        payload = ExecuteActionResponseBuilder().build(context)
        self.assertEqual(payload['pod_cod'], {})
        self.assertEqual(len(payload['timeline_preview']['timeline_preview']), 1)

    def test_normalize_job_type_aliases(self):
        orch = ExecuteActionOrchestrator()
        self.assertEqual(orch._normalize_job_type('empty_move'), 'movement')
        self.assertEqual(orch._normalize_job_type('SHIPMENT'), 'shipment')

    def test_orchestrator_requires_idempotency_key(self):
        from mobile_api.execution.guards.execution_idempotency_guard import (
            ExecutionIdempotencyGuard,
        )

        ctx = ExecuteActionContext(
            driver=object(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='1',
            action_code='A1',
            payload={},
        )
        with self.assertRaises(ExecuteActionError) as exc:
            ExecutionIdempotencyGuard().assert_idempotency_key_present(ctx)
        self.assertEqual(exc.exception.code, 'idempotency_key_required')
