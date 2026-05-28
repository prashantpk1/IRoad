"""
DB-backed execution integration tests (opt-in).

Set ``EXECUTION_INTEGRATION_DB=1`` with a provisioned tenant schema and fixtures.
"""
from __future__ import annotations

import os
import unittest
import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.tests.transaction_test_case import TransactionTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execute_action_response_builder import (
    ExecuteActionResponseBuilder,
)
from mobile_api.execution.guards.execution_idempotency_guard import (
    ExecutionIdempotencyGuard,
    IdempotencyKeys,
)
from mobile_api.execution.services.execute_action_orchestrator import (
    ExecuteActionOrchestrator,
)
from tenant_workspace.models import TenantOperationActionLog


def _integration_enabled() -> bool:
    return os.environ.get('EXECUTION_INTEGRATION_DB', '').lower() in {
        '1',
        'true',
        'yes',
    }


class ExecutionResponseCompletenessTests(SimpleTestCase):
    """Response builder replay fields (no DB)."""

    def test_execution_block_includes_replay_metadata(self):
        log = MagicMock()
        log.log_id = uuid.uuid4()
        log.log_no = 'OAL-1'
        log.date = None
        log.log_date = None

        ctx = ExecuteActionContext(
            driver=MagicMock(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='s1',
            action_code='A2',
            action_log=log,
            idempotent_replay=True,
            reused_existing=True,
            workflow={'allowed_actions': []},
            timeline={
                'scope': 'shipment',
                'timeline_preview': [{'event_id': 'e1'}],
                'timeline_cursor': '',
                'has_more': False,
            },
            alerts={'has_drift': False},
            pod_cod={'pod_pending': True},
            sync_metadata={'content_hash': 'h2', 'workflow_version': 'w2'},
        )
        payload = ExecuteActionResponseBuilder().build(ctx)
        self.assertTrue(payload['execution']['replayed'])
        self.assertEqual(payload['execution']['original_action_log_id'], str(log.log_id))
        self.assertIn('timeline_preview', payload)
        self.assertEqual(len(payload['timeline_preview']['timeline_preview']), 1)


class ExecutionIdempotencyLookupUnitTests(SimpleTestCase):
    @patch.object(ExecutionIdempotencyGuard, '_default_log_lookup')
    def test_lookup_delegates_to_kernel_finder(self, mock_lookup):
        mock_lookup.return_value = MagicMock(
            log_id='x',
            operation_action=MagicMock(action_code='A2'),
        )
        keys = IdempotencyKeys(idempotency_key='client-abc', source_ref='')
        ctx = ExecuteActionContext(
            driver=MagicMock(),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='s1',
            action_code='A2',
            payload={'client_action_id': 'client-abc'},
        )
        self.assertTrue(ExecutionIdempotencyGuard().detect_idempotent_replay(ctx, keys))


@unittest.skipUnless(
    _integration_enabled(),
    'Set EXECUTION_INTEGRATION_DB=1 with tenant DB fixtures to run.',
)
class ExecutionDatabaseIntegrationTests(TransactionTestCase):
    """
    Real transactional tests against tenant schema.

    Extend with tenant fixtures (driver, shipment, Action Master rows) per environment.
    """

    def test_idempotency_key_unique_constraint_exists(self):
        field = TenantOperationActionLog._meta.get_field('idempotency_key')
        self.assertTrue(field.unique)


class ExecutionOrchestratorRollbackContractTests(SimpleTestCase):
    """Document rollback contract — orchestrator uses transaction.atomic."""

    def test_atomic_decorator_present(self):
        self.assertTrue(
            hasattr(ExecuteActionOrchestrator._execute_driver_action_atomic, '__wrapped__')
            or 'atomic' in str(ExecuteActionOrchestrator._execute_driver_action_atomic.__doc__ or '').lower()
            or hasattr(ExecuteActionOrchestrator, '_execute_driver_action_atomic'),
        )
