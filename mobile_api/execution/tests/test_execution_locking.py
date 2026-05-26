"""
Execution entity locking tests.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.guards.execution_locking import lock_execution_entities


class ExecutionLockingTests(SimpleTestCase):
    @patch('mobile_api.execution.guards.execution_locking.mobile_execution_entity_locking_enabled', return_value=True)
    @patch('tenant_workspace.models.TenantShipment')
    def test_shipment_select_for_update(self, mock_model, _enabled):
        locked = SimpleNamespace(pk='ship-1', shipment_id='ship-1', booking_id='bk-1')
        qs = MagicMock()
        qs.filter.return_value.first.return_value = locked
        mock_model.objects.select_for_update.return_value = qs

        ctx = ExecuteActionContext(
            driver=SimpleNamespace(pk='d1'),
            tenant_schema='tenant_test',
            user_id='u1',
            job_type='shipment',
            job_id='ship-1',
            action_code='A2',
            shipment=SimpleNamespace(pk='ship-1', shipment_id='ship-1'),
        )
        lock_execution_entities(ctx, operation_action=None)
        mock_model.objects.select_for_update.assert_called_once()
        self.assertIs(ctx.shipment, locked)
