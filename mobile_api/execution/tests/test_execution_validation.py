"""
Execution validation layer tests (Action Master, stale sync, idempotency).
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from uuid import uuid4

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
                'workflow_version': 'wf-old',
            },
        )
        with self.assertRaises(ExecuteActionError) as exc:
            StaleExecutionGuard().assert_not_stale(ctx)
        self.assertEqual(exc.exception.code, 'stale_content_hash')
        self.assertTrue(exc.exception.validation_error['refresh_required'])
        self.assertIn('sync_metadata', exc.exception.validation_error)

    def test_matching_workflow_version_ignores_content_hash_mismatch(self):
        ctx = _context(
            payload={
                'client_action_id': 'cid-1',
                'content_hash': 'hash-stale',
                'workflow_version': 'wf-server',
            },
        )
        StaleExecutionGuard().assert_not_stale(ctx)

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
            shipment_id='ship-1',
        )
        guard = ExecutionIdempotencyGuard(
            log_lookup=lambda _keys: existing_log,
        )
        keys = IdempotencyKeys(idempotency_key='client-uuid-1', source_ref='')
        self.assertTrue(guard.detect_idempotent_replay(ctx, keys))
        self.assertTrue(ctx.idempotent_replay)
        self.assertTrue(ctx.reused_existing)

    def test_replay_rejected_when_log_belongs_to_other_movement(self):
        ctx = _context(action_code='EM2', job_type='movement')
        ctx.movement = SimpleNamespace(pk=uuid4())
        other_movement_id = uuid4()
        existing_log = SimpleNamespace(
            operation_action=SimpleNamespace(action_code='EM2'),
            truck_movement_id=other_movement_id,
        )
        guard = ExecutionIdempotencyGuard(
            log_lookup=lambda _keys: existing_log,
        )
        keys = IdempotencyKeys(idempotency_key='em-depart-shared-key', source_ref='')
        with self.assertRaises(ExecuteActionError) as exc:
            guard.detect_idempotent_replay(ctx, keys)
        self.assertEqual(exc.exception.code, 'idempotency_key_scope_mismatch')

    def test_replay_allowed_when_log_belongs_to_same_movement(self):
        movement_id = uuid4()
        ctx = _context(action_code='EM2', job_type='movement')
        ctx.movement = SimpleNamespace(pk=movement_id)
        existing_log = SimpleNamespace(
            operation_action=SimpleNamespace(action_code='EM2'),
            truck_movement_id=movement_id,
        )
        guard = ExecutionIdempotencyGuard(
            log_lookup=lambda _keys: existing_log,
        )
        keys = IdempotencyKeys(idempotency_key='em-depart-same', source_ref='')
        self.assertTrue(guard.detect_idempotent_replay(ctx, keys))
        self.assertTrue(ctx.idempotent_replay)

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

    def test_pod_execute_blocked_when_shipment_document_missing(self):
        ctx = _context(action_code='OA-0009')
        ctx.shipment = SimpleNamespace(pk='sh-1', pod_doc_count=2, booking_id=None)
        action = SimpleNamespace(
            action_code='OA-0009',
            english_label='POD',
            auto_pod_post=True,
        )
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = action

        with patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value=None,
        ), patch.object(
            ExecutionReconcileService,
            'apply_status_overlays',
            _fake_apply_overlays,
        ), patch.object(
            svc,
            '_action_in_allowed_list',
            return_value=True,
        ), patch(
            'iroad_tenants.operation_runtime.pod_action.shipment_has_layer_zero_document',
            return_value=False,
        ):
            with self.assertRaises(ExecuteActionError) as exc:
                svc.validate_pre_execute_after_idempotency(ctx)
        self.assertEqual(exc.exception.code, 'shipment_document_required')
        self.assertIn('shipment document', str(exc.exception).casefold())

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


class HardPodCustodyExecuteBypassTests(SimpleTestCase):
    def test_stale_guard_skips_internal_hard_pod_chain(self):
        guard = StaleExecutionGuard()
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='shipment',
            job_id='ship-1',
            action_code='OA-0008',
            payload={'execution_origin': 'hard_pod_custody_submit'},
            sync_metadata={'content_hash': 'server', 'workflow_version': 'wf'},
        )
        guard.assert_not_stale(ctx)

    def test_stale_guard_skips_scope_redirect(self):
        guard = StaleExecutionGuard()
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='booking',
            job_id='booking-1',
            action_code='OA-0001',
            payload={
                'content_hash': 'shipment-hash',
                'workflow_version': 'wf-1',
            },
            resolver_meta={'backload_booking_redirect': True},
            sync_metadata={
                'content_hash': 'booking-hash',
                'workflow_version': 'wf-2',
            },
        )
        guard.assert_not_stale(ctx)

    @patch(
        'mobile_api.hard_pod.services.hard_pod_execute_integration.HardPodExecuteIntegrationService._custody_promoted_for_shipment',
        return_value=False,
    )
    def test_hard_copy_custody_execute_skips_digital_photo_requirements(self, _mock_promoted):
        from mobile_api.execution.evidence.evidence_validation_service import (
            EvidenceValidationService,
        )

        action = SimpleNamespace(
            action_code='OA-0008',
            auto_pod_post=True,
            hard_copy_collection=True,
        )
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='shipment',
            job_id='ship-1',
            action_code='OA-0008',
            payload={
                'custody_submission_id': str(uuid4()),
                'capture_mode': 'hard_copy_confirmation',
            },
            shipment=_shipment(status='POD_Submitted'),
            operation_action=action,
        )
        service = EvidenceValidationService()
        service.validate_required_evidence(ctx)

    def test_label_only_pod_hard_copy_execute_allowed_outside_workflow_list(self):
        """OA-* POD by english_label — step 2 execute after custody submit."""
        ctx = _context(
            action_code='OA-0009',
            authoritative={'allowed_actions': [{'action_code': 'OA-0010'}]},
        )
        ctx.shipment = SimpleNamespace(
            pk='ship-1',
            pod_type='Hard',
            order_type='COD',
        )
        action = SimpleNamespace(
            action_code='OA-0009',
            english_label='POD',
            auto_pod_post=False,
            hard_copy_collection=False,
        )
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        with patch(
            'iroad_tenants.operation_execution._combined_pod_allows_hard_copy_retry',
            return_value=True,
        ), patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value=None,
        ):
            self.assertTrue(svc._combined_pod_execute_allowed(ctx, action))

    def test_booking_execute_pivots_to_shipment_before_pod_validation(self):
        """Hard POD confirm on booking scope must attach shipment before policy check."""
        booking = SimpleNamespace(
            pk='bk-1',
            booking_id='bk-1',
            booking_status='Confirmed',
        )
        shipment = SimpleNamespace(
            pk='ship-1',
            shipment_id='ship-1',
            pod_type='Hard',
            order_type='COD',
            booking=booking,
        )
        ctx = _context(
            job_type='booking',
            job_id='bk-1',
            action_code='OA-0009',
            shipment=None,
            booking=booking,
            payload={
                'client_action_id': 'client-uuid-1',
                'custody_submission_id': str(uuid4()),
                'capture_mode': 'hard_copy_confirmation',
            },
        )
        action = SimpleNamespace(
            pk=uuid4(),
            action_code='OA-0009',
            english_label='POD',
            auto_pod_post=True,
            hard_copy_collection=True,
            status='Active',
        )
        svc = ExecutionValidationService(operation_action_model=MagicMock())
        svc._operation_action_model.objects.filter.return_value.first.return_value = action
        with patch(
            'mobile_api.execution.services.execution_validation_service.finalize_execute_scope',
            side_effect=lambda context: (
                setattr(context, 'shipment', shipment)
                or setattr(context, 'job_type', 'shipment')
                or setattr(context, 'job_id', 'ship-1')
                or True
            ),
        ), patch.object(
            ExecutionReconcileService,
            'apply_status_overlays',
            _fake_apply_overlays,
        ), patch.object(
            svc,
            '_booking_item_type',
            return_value='Outbound',
        ), patch.object(
            OperationExecutionService,
            'validate_operation_action_allowed',
            return_value=None,
        ) as mock_validate, patch.object(
            svc,
            '_action_in_allowed_list',
            return_value=True,
        ):
            svc.validate_action_master(ctx)
            mock_validate.assert_called_once()
            self.assertIs(ctx.shipment, shipment)


class HardPodCustodyRecoveryGuardTests(SimpleTestCase):
    def test_recovery_skipped_while_promotion_active(self):
        from mobile_api.hard_pod.services.hard_pod_custody_recovery import (
            hard_pod_promotion_guard,
            try_recover_unpromoted_hard_pod_custody,
        )

        driver = _driver()
        shipment = _shipment()
        with hard_pod_promotion_guard():
            self.assertFalse(
                try_recover_unpromoted_hard_pod_custody(
                    driver=driver,
                    shipment=shipment,
                    tenant_schema='tenant_test',
                ),
            )
