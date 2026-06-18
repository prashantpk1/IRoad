"""
Execution validation layer tests (Action Master, stale sync, idempotency).
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.guards.execution_idempotency_guard import (
    ExecutionIdempotencyGuard,
    IdempotencyKeys,
)
from mobile_api.execution.guards.stale_execution_guard import StaleExecutionGuard
from mobile_api.execution.services.execution_reconcile_service import (
    ExecutionReconcileService,
)
from mobile_api.execution.services.execution_validation_service import (
    ExecutionValidationService,
)
from iroad_tenants.services.operation_execution_service import OperationExecutionService


def _fake_apply_overlays(_self, _ctx):
    @contextmanager
    def _cm():
        yield

    return _cm()


def _driver():
    return SimpleNamespace(pk='drv-1', driver_id='drv-1', driver_status='Active')


def _shipment(status='Booked'):
    return SimpleNamespace(
        pk='ship-1',
        shipment_id='ship-1',
        shipment_no='SHP-001',
        shipment_status=status,
        booking_item_type='outbound',
        booking=SimpleNamespace(pk='bk-1'),
    )


def _context(**kwargs):
    defaults = dict(
        driver=_driver(),
        tenant_schema='tenant_test',
        user_id='user-1',
        job_type='shipment',
        job_id='ship-1',
        action_code='A2',
        payload={
            'client_action_id': 'client-uuid-1',
            'content_hash': 'hash-server',
            'workflow_version': 'wf-server',
        },
        shipment=_shipment(),
        authoritative={
            'allowed_actions': [
                {'action_code': 'A2'},
                {'action_code': 'A3'},
            ],
            'sync_metadata': {
                'content_hash': 'hash-server',
                'workflow_version': 'wf-server',
                'entity_versions': {'shipment': 'ent-ship-v1'},
            },
        },
        sync_metadata={
            'content_hash': 'hash-server',
            'workflow_version': 'wf-server',
            'entity_versions': {'shipment': 'ent-ship-v1'},
        },
        reconciliation={
            'shipment': {
                'authoritative_status': 'In Transit',
                'column_status': 'Booked',
            },
        },
    )
    defaults.update(kwargs)
    return ExecuteActionContext(**defaults)


def _validation_patches(*, replay: bool = False):
    return (
        patch.object(
            ExecutionIdempotencyGuard,
            'detect_idempotent_replay',
            return_value=replay,
        ),
        patch.object(
            ExecutionIdempotencyGuard,
            'normalize_request_keys',
            return_value=IdempotencyKeys(
                idempotency_key='client-uuid-1',
                source_ref='shipment:ship-1:A2',
            ),
        ),
        patch.object(ExecutionReconcileService, 'apply_status_overlays', _fake_apply_overlays),
        patch.object(
            ExecutionValidationService,
            '_attach_operational_issue_warnings',
        ),
    )


class ExecutionValidationTests(SimpleTestCase):
    def test_allowed_action_passes(self):
        ctx = _context()
        action = SimpleNamespace(action_code='A2', pk='act-2')
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = action

        p_replay, p_keys, p_overlay, p_issues = _validation_patches()
        with p_replay, p_keys, p_overlay, p_issues, patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value=None,
        ):
            result = svc.validate_pre_execute(ctx)
        self.assertTrue(result.ok)
        self.assertFalse(result.idempotent_replay)
        self.assertEqual(ctx.operation_action, action)

    def test_forbidden_action_not_in_allowed_list(self):
        ctx = _context(action_code='A99')
        action = SimpleNamespace(action_code='A99', pk='act-99', english_label='A99')
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = action

        p_replay, p_keys, p_overlay, p_issues = _validation_patches()
        with p_replay, p_keys, p_overlay, p_issues, patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value=None,
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                svc.validate_pre_execute(ctx)
        self.assertEqual(exc.exception.code, 'action_not_allowed')
        self.assertTrue(exc.exception.refresh_required)
        self.assertEqual(exc.exception.validation_error['error_code'], 'action_not_allowed')

    def test_forbidden_action_includes_next_action_hint(self):
        ctx = _context(action_code='A7')
        ctx.workflow = {'allowed_actions': [], 'current_stage': 'Completed'}
        ctx.pod_cod = {'pod_pending': False, 'pod_compliant': True}
        ctx.shipment = SimpleNamespace(
            shipment_status='Closed',
            order_type='COD',
        )
        action = SimpleNamespace(action_code='A7', pk='act-7')
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = action

        p_replay, p_keys, p_overlay, p_issues = _validation_patches()
        with p_replay, p_keys, p_overlay, p_issues, patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value=None,
        ), patch.object(
            svc,
            '_action_in_allowed_list',
            return_value=False,
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                svc.validate_action_master(ctx)
        hint = exc.exception.validation_error.get('next_action_hint') or {}
        self.assertEqual(hint.get('action'), 'go_to_dashboard')
        self.assertTrue(hint.get('job_closed'))

    def test_stale_content_hash(self):
        ctx = _context(
            payload={
                'client_action_id': 'cid-1',
                'content_hash': 'hash-stale',
                'workflow_version': 'wf-server',
            },
        )
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_content_hash')
        self.assertTrue(exc.exception.validation_error['refresh_required'])

    def test_stale_workflow_version(self):
        ctx = _context(
            payload={
                'client_action_id': 'cid-1',
                'content_hash': 'hash-server',
                'workflow_version': 'wf-old',
            },
        )
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_workflow_version')

    def test_stale_entity_version(self):
        ctx = _context(
            payload={
                'client_action_id': 'cid-1',
                'content_hash': 'hash-server',
                'workflow_version': 'wf-server',
                'entity_versions': {'shipment': 'ent-old'},
            },
        )
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_entity_version')

    def test_missing_idempotency_key(self):
        ctx = _context(payload={})
        with self.assertRaises(ExecuteActionError) as exc:
            ExecutionIdempotencyGuard().assert_idempotency_key_present(ctx)
        self.assertEqual(exc.exception.code, 'idempotency_key_required')
        self.assertFalse(exc.exception.refresh_required)

    def test_replay_retry_attaches_existing_log(self):
        ctx = _context()
        existing_log = SimpleNamespace(
            operation_action=SimpleNamespace(action_code='A2'),
        )
        guard = ExecutionIdempotencyGuard(
            log_lookup=lambda _keys: existing_log,
        )
        keys = IdempotencyKeys(idempotency_key='client-uuid-1', source_ref='')
        self.assertTrue(guard.detect_idempotent_replay(ctx, keys))
        self.assertTrue(ctx.idempotent_replay)
        self.assertTrue(ctx.reused_existing)

    def test_idempotent_replay_short_circuits_validation(self):
        ctx = _context()
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        with patch.object(
            ExecutionIdempotencyGuard,
            'normalize_request_keys',
            return_value=IdempotencyKeys(idempotency_key='k', source_ref=''),
        ), patch.object(
            ExecutionIdempotencyGuard,
            'detect_idempotent_replay',
            return_value=True,
        ), patch.object(svc, 'validate_action_master') as mock_validate:
            result = svc.validate_pre_execute(ctx)
        self.assertTrue(result.idempotent_replay)
        mock_validate.assert_not_called()

    def test_replay_skips_stale_check(self):
        ctx = _context(
            payload={
                'client_action_id': 'cid-1',
                'expected_content_hash': 'wrong-hash',
            },
            idempotent_replay=True,
        )
        StaleExecutionGuard().assert_not_stale(ctx)

    def test_action_master_mismatch_on_replay(self):
        ctx = _context(action_code='A2')
        existing_log = SimpleNamespace(
            operation_action=SimpleNamespace(action_code='A3'),
        )
        guard = ExecutionIdempotencyGuard(
            log_lookup=lambda _keys: existing_log,
        )
        with self.assertRaises(ExecuteActionError) as exc:
            guard.detect_idempotent_replay(
                ctx,
                IdempotencyKeys(idempotency_key='k', source_ref=''),
            )
        self.assertEqual(exc.exception.code, 'action_master_mismatch')

    def test_policy_engine_forbidden_message(self):
        ctx = _context()
        action = SimpleNamespace(action_code='A2')
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = action

        with patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value='Action not permitted for current status.',
        ), patch.object(
            ExecutionReconcileService,
            'apply_status_overlays',
            _fake_apply_overlays,
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                svc.validate_action_master(ctx)
        self.assertEqual(exc.exception.code, 'action_not_allowed')

    def test_action_not_found(self):
        ctx = _context(action_code='UNKNOWN')
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = None
        with self.assertRaises(ExecuteActionError) as exc:
            svc.resolve_operation_action(ctx)
        self.assertEqual(exc.exception.code, 'action_not_found')
        self.assertTrue(exc.exception.validation_error['refresh_required'])

    def test_client_action_id_maps_to_idempotency_key(self):
        ctx = _context(payload={'client_action_id': '  uuid-abc  '})
        keys = ExecutionIdempotencyGuard().normalize_request_keys(ctx)
        self.assertEqual(keys.idempotency_key, 'uuid-abc')
        self.assertEqual(ctx.idempotency_key, 'uuid-abc')

    def test_booking_item_type_resolves_backload_after_outbound_closed(self):
        booking = SimpleNamespace(
            trip_type='Round',
            loading_booking_item='Outbound',
            shipments=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        shipment_status='Closed',
                        booking_item_type='Outbound',
                        shipment_sequence=1,
                    ),
                ],
            ),
        )
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='booking',
            job_id='bk-1',
            action_code='A1',
            payload={'client_action_id': 'c1'},
            booking=booking,
        )
        self.assertEqual(
            ExecutionValidationService._booking_item_type(ctx),
            'Backload',
        )
