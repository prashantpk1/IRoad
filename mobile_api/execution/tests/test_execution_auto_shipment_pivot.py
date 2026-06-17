"""
Post-execute booking → shipment scope pivot after Auto Shipment birth at A4.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.services.execution_context_adapter import (
    pivot_execute_context_to_born_shipment,
)
from mobile_api.execution.services.execution_reconcile_service import (
    ExecutionReconcileService,
)


def _booking(pk='bk-1'):
    return SimpleNamespace(
        pk=pk,
        booking_id=pk,
        booking_no='BK-001',
        booking_status='Confirmed',
    )


def _shipment(pk='ship-1', *, status='Loaded'):
    return SimpleNamespace(
        pk=pk,
        shipment_id=pk,
        shipment_no='SH-001',
        shipment_status=status,
        booking_item_type='Outbound',
        booking=_booking(),
    )


class ExecuteAutoShipmentPivotTests(SimpleTestCase):
    def _context(self, *, job_type='booking', job_id='bk-1', **kwargs):
        return ExecuteActionContext(
            driver=SimpleNamespace(pk='drv-1'),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type=job_type,
            job_id=job_id,
            action_code='A4',
            booking=_booking(),
            **kwargs,
        )

    def test_pivot_noop_when_not_booking_scope(self):
        context = self._context(job_type='shipment', job_id='ship-1')
        self.assertFalse(pivot_execute_context_to_born_shipment(context))
        self.assertEqual(context.job_type, 'shipment')

    def test_pivot_noop_without_shipment_on_action_log(self):
        context = self._context(action_log=SimpleNamespace(shipment_id=None))
        self.assertFalse(pivot_execute_context_to_born_shipment(context))
        self.assertEqual(context.job_type, 'booking')

    @patch('mobile_api.job_detail.guards.entity_lookup.lookup_shipment_by_reference')
    def test_pivot_switches_scope_when_action_log_links_shipment(
        self,
        lookup_mock,
    ):
        shipment = _shipment()
        lookup_mock.return_value = shipment
        context = self._context(
            action_log=SimpleNamespace(
                shipment_id='ship-1',
                shipment=None,
            ),
        )

        self.assertTrue(pivot_execute_context_to_born_shipment(context))
        self.assertEqual(context.job_type, 'shipment')
        self.assertEqual(context.job_id, 'ship-1')
        self.assertIs(context.shipment, shipment)
        lookup_mock.assert_called_once_with('ship-1')

    @patch('mobile_api.job_detail.guards.entity_lookup.lookup_shipment_by_reference')
    def test_pivot_resets_projection_cache_scope(self, lookup_mock):
        shipment = _shipment()
        lookup_mock.return_value = shipment
        cache = MagicMock()
        context = self._context(
            action_log=SimpleNamespace(shipment_id='ship-1'),
        )
        context._execution_projection_cache = cache  # type: ignore[attr-defined]

        pivot_execute_context_to_born_shipment(context)
        cache.reset_job_detail_scope.assert_called_once()

    @patch(
        'mobile_api.execution.services.execution_reconcile_service.ExecutionProjectionCache',
    )
    @patch(
        'mobile_api.execution.services.execution_reconcile_service.pivot_execute_context_to_born_shipment',
        return_value=True,
    )
    def test_reconcile_post_execute_pivots_before_projection(
        self,
        pivot_mock,
        cache_cls_mock,
    ):
        context = self._context()
        cache = MagicMock()
        cache_cls_mock.attach.return_value = cache
        svc = ExecutionReconcileService()

        svc.reconcile_post_execute(context)

        pivot_mock.assert_called_once_with(context)
        cache_cls_mock.attach.assert_called_once_with(context)
        cache.build_post_execute_sections.assert_called_once()
