"""
Pre-execute resolve + ownership + reconcile tests (no kernel / no DB writes).
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.guards.execution_ownership_guard import ExecutionOwnershipGuard
from mobile_api.execution.guards.stale_execution_guard import StaleExecutionGuard
from mobile_api.execution.services.execution_reconcile_service import ExecutionReconcileService


@contextmanager
def _fake_schema(_name):
    yield


def _driver(pk='drv-1'):
    return SimpleNamespace(
        pk=pk,
        driver_id=pk,
        driver_status='Active',
        user_id='user-1',
    )


def _shipment(pk='ship-1', status='Booked'):
    return SimpleNamespace(
        pk=pk,
        shipment_id=pk,
        shipment_no='SHP-001',
        shipment_status=status,
        booking_item_type='outbound',
        driver_id='drv-1',
        booking_id='bk-1',
        booking=SimpleNamespace(
            pk='bk-1',
            assigned_driver_id='drv-1',
            booking_line_backload_driver_id=None,
        ),
    )


def _movement(pk='mov-1', status='Planned'):
    return SimpleNamespace(
        pk=pk,
        movement_id=pk,
        movement_no='MOV-001',
        status=status,
        movement_source='Empty',
        driver_id='drv-1',
        shipment_id=None,
    )


class ExecutionPrepareTests(SimpleTestCase):
    def _context(self, job_type='shipment', job_id='ship-1', **kwargs):
        return ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type=job_type,
            job_id=job_id,
            action_code='A1',
            **kwargs,
        )

    @patch(
        'mobile_api.execution.services.execution_projection_cache.build_job_detail_sync_metadata'
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.resolve_content_hash',
        return_value='hash-server',
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.build_workflow_section'
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.reconcile_job_detail_entities'
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.load_projection_cache'
    )
    @patch.object(ExecutionOwnershipGuard, 'resolve_entity')
    @patch.object(ExecutionOwnershipGuard, 'assert_driver_may_execute')
    def test_shipment_authoritative_context_shape(
        self,
        _assert_own,
        mock_resolve,
        _load_cache,
        mock_reconcile,
        mock_workflow,
        _resolve_hash,
        mock_sync_meta,
    ):
        shipment = _shipment(status='Booked')
        ctx = self._context()

        def _fill_resolve(context):
            context.shipment = shipment
            context.booking = shipment.booking
            context.resolver_meta = {
                'entity': {'shipment_id': 'ship-1', 'shipment_no': 'SHP-001'},
            }

        mock_resolve.side_effect = _fill_resolve
        mock_reconcile.side_effect = lambda jd_ctx, **kw: setattr(
            jd_ctx,
            'reconciliation',
            {
                'workflow_reconciled': True,
                'shipment': {
                    'authoritative_status': 'In Transit',
                    'column_status': 'Booked',
                    'status_source': 'action_log',
                    'drift_detected': True,
                    'drift_reason': 'status_mismatch',
                },
            },
        )
        mock_workflow.return_value = {
            'current_stage': 'in_transit',
            'allowed_actions': [{'action_code': 'A2'}],
            'next_action': {'action_code': 'A2'},
            'primary_action': {},
        }
        mock_sync_meta.return_value = {
            'content_hash': 'hash-server',
            'workflow_version': 'wf-v1',
            'entity_versions': {'shipment': 'v1'},
        }

        auth = ExecutionReconcileService().prepare_pre_execute(ctx)

        self.assertEqual(auth['job_type'], 'shipment')
        self.assertEqual(auth['entity']['shipment_status'], 'In Transit')
        self.assertEqual(auth['entity']['status_authority'], 'action_log')
        self.assertEqual(auth['reconciled_state']['authoritative_status'], 'In Transit')
        self.assertTrue(auth['reconciled_state']['drift_detected'])
        self.assertEqual(len(auth['allowed_actions']), 1)
        self.assertEqual(auth['allowed_actions'][0]['action_code'], 'A2')
        self.assertEqual(auth['sync_metadata']['content_hash'], 'hash-server')

    @patch(
        'mobile_api.execution.services.execution_projection_cache.build_job_detail_sync_metadata',
        return_value={'content_hash': 'm-hash'},
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.resolve_content_hash',
        return_value='m-hash',
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.build_workflow_section',
        return_value={'allowed_actions': [], 'current_stage': 'planned'},
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.reconcile_job_detail_entities'
    )
    @patch(
        'mobile_api.execution.services.execution_projection_cache.load_projection_cache'
    )
    @patch.object(ExecutionOwnershipGuard, 'resolve_entity')
    @patch.object(ExecutionOwnershipGuard, 'assert_driver_may_execute')
    def test_movement_authoritative_context_omits_pod_path(
        self,
        _assert_own,
        mock_resolve,
        _load_cache,
        mock_reconcile,
        _workflow,
        _hash,
        _sync,
    ):
        movement = _movement()
        ctx = self._context(job_type='movement', job_id='mov-1')

        def _fill_resolve(context):
            context.movement = movement
            context.resolver_meta = {
                'entity': {'movement_id': 'mov-1', 'movement_no': 'MOV-001'},
            }

        mock_resolve.side_effect = _fill_resolve
        mock_reconcile.side_effect = lambda jd_ctx, **kw: setattr(
            jd_ctx,
            'reconciliation',
            {
                'workflow_reconciled': True,
                'movement': {
                    'authoritative_status': 'Started',
                    'column_status': 'Planned',
                    'status_source': 'action_log',
                    'drift_detected': False,
                },
            },
        )

        with patch(
            'mobile_api.execution.services.execution_projection_cache.reconcile_job_detail_pod_cod',
        ) as mock_pod:
            auth = ExecutionReconcileService().prepare_pre_execute(ctx)
            mock_pod.assert_not_called()

        self.assertEqual(auth['job_type'], 'movement')
        self.assertEqual(auth['entity']['status'], 'Started')
        self.assertEqual(auth['reconciled_state']['authoritative_status'], 'Started')

    def test_wrong_tenant_raises(self):
        ctx = self._context()
        ctx.tenant_schema = ''
        guard = ExecutionOwnershipGuard()
        with self.assertRaises(ExecuteActionError) as exc:
            guard.assert_tenant_and_driver(ctx)
        self.assertEqual(exc.exception.code, 'tenant_required')

    def test_wrong_driver_forbidden(self):
        shipment = _shipment()
        shipment.booking.assigned_driver_id = 'other-driver'
        shipment.driver_id = None
        mock_ship_resolver = MagicMock()
        mock_ship_resolver.resolve.return_value = SimpleNamespace(
            shipment=shipment,
            booking=shipment.booking,
            resolve_context=SimpleNamespace(
                ok=True,
                to_resolver_meta=lambda: {},
            ),
            error_code=None,
            error_message=None,
        )
        ctx = self._context()
        guard = ExecutionOwnershipGuard(shipment_resolver=mock_ship_resolver)
        guard.resolve_entity(ctx)
        with self.assertRaises(ExecuteActionError) as exc:
            guard.assert_driver_may_execute(ctx)
        self.assertEqual(exc.exception.code, 'forbidden')
        self.assertEqual(exc.exception.http_status, 403)

    def test_stale_workflow_content_hash_mismatch(self):
        ctx = self._context(
            payload={
                'content_hash': 'hash-client',
                'workflow_version': 'wf-v1',
            },
        )
        ctx.sync_metadata = {'content_hash': 'hash-server', 'workflow_version': 'wf-v1'}
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_content_hash')
        self.assertEqual(exc.exception.http_status, 409)

    def test_stale_workflow_version_mismatch(self):
        ctx = self._context(
            payload={
                'content_hash': 'hash-server',
                'workflow_version': 'wf-old',
            },
        )
        ctx.sync_metadata = {
            'content_hash': 'hash-server',
            'workflow_version': 'wf-new',
        }
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_workflow_version')

    def test_reconciled_overlay_restores_column_after_context(self):
        """``apply_status_overlays`` must temporarily set log-primary status."""
        shipment = _shipment(status='Booked')
        ctx = self._context()
        ctx.shipment = shipment
        ctx.reconciliation = {
            'shipment': {
                'authoritative_status': 'In Transit',
                'column_status': 'Booked',
                'status_source': 'action_log',
                'drift_detected': True,
            },
        }
        captured: list[str] = []
        svc = ExecutionReconcileService()
        with svc.apply_status_overlays(ctx):
            captured.append(str(shipment.shipment_status))
        self.assertEqual(captured, ['In Transit'])
        self.assertEqual(shipment.shipment_status, 'Booked')
