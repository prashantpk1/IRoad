"""
Execute Action orchestrator pipeline tests (mocked kernel / no tenant DB).
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase

from mobile_api.execution.dto.execute_action_context import ExecuteActionContext
from mobile_api.execution.dto.execute_action_result import ExecuteActionResult
from mobile_api.execution.exceptions import ExecuteActionError
from mobile_api.execution.services.execute_action_orchestrator import (
    ExecuteActionOrchestrator,
)


@contextmanager
def _fake_schema(_name):
    yield


def _driver():
    return SimpleNamespace(
        pk='drv-1',
        driver_id='drv-1',
        driver_name='Test Driver',
        user_id='user-1',
    )


def _shipment():
    return SimpleNamespace(
        pk='ship-1',
        shipment_id='ship-1',
        shipment_no='SHP-1',
        shipment_status='In Transit',
        booking_item_type='outbound',
        order_type='COD',
        booking=SimpleNamespace(pk='bk-1'),
        truck=None,
    )


def _movement():
    return SimpleNamespace(
        pk='mov-1',
        movement_id='mov-1',
        movement_no='MOV-1',
        status='Started',
        truck=None,
    )


def _action_log():
    return SimpleNamespace(
        log_id='log-1',
        log_no='OAL-001',
        log_date=None,
        operation_action=_action('A2'),
    )


def _action(code: str, *, label: str = ''):
    return SimpleNamespace(
        action_code=code,
        english_label=label,
    )


def _collect_payment_action():
    return SimpleNamespace(
        action_code='A9',
        english_label='Collect Payment',
        auto_treasury_post=True,
        action_scope='Job',
        sequence_number=9,
    )


class ExecuteActionOrchestratorTests(SimpleTestCase):
    def _orchestrator(self):
        return ExecuteActionOrchestrator()

    def _base_payload(self):
        return {
            'client_action_id': 'client-uuid-execute-1',
            'content_hash': 'hash-pre',
            'workflow_version': 'wf-pre',
            'latitude': '25.0',
            'longitude': '55.0',
            'notes': 'ok',
        }

    def test_shipment_execute_success(self):
        orch = self._orchestrator()
        context_holder: dict[str, ExecuteActionContext] = {}

        def _capture_prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.booking = ctx.shipment.booking
            ctx.workflow = {
                'allowed_actions': [{'action_code': 'A2'}],
                'next_action': {'action_code': 'A2'},
                'primary_action': {'action_code': 'A2'},
            }
            ctx.sync_metadata = {'content_hash': 'h1', 'workflow_version': 'v1'}
            return {}

        def _capture_build(ctx, **kw):
            context_holder['ctx'] = ctx
            return ExecuteActionResult(
                payload={
                    'execution': {'action_log_id': 'log-1'},
                    'workflow': ctx.workflow,
                    'pod_cod': {'pod_pending': True},
                    'round_trip': {},
                    'sync_metadata': ctx.sync_metadata,
                },
                http_status=201,
            )

        kernel_result = SimpleNamespace(
            action_log=_action_log(),
            reused_existing=False,
        )

        with patch.object(
            orch._reconcile_service,
            'prepare_pre_execute',
            side_effect=_capture_prepare,
        ), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(
                ok=True,
                idempotent_replay=False,
                idempotency_keys=None,
            ),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_action('A2'),
        ), patch.object(
            orch,
            '_execute_kernel',
            return_value=kernel_result,
        ) as mock_kernel, patch.object(
            orch._media_service,
            'persist_execution_media',
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            side_effect=_capture_build,
        ):
            result = orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant_test',
                job_type='shipment',
                job_id='ship-1',
                action_code='A2',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='user-1',
            )

        self.assertEqual(result.http_status, 201)
        mock_kernel.assert_called_once()
        self.assertEqual(context_holder['ctx'].action_log, kernel_result.action_log)

    def test_a9_attaches_payment_bundle_and_status_blocks(self):
        orch = self._orchestrator()

        def _capture_prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.booking = ctx.shipment.booking
            ctx.workflow = {
                'allowed_actions': [{'action_code': 'A9'}],
                'next_action': {'action_code': 'A9'},
                'primary_action': {'action_code': 'A9'},
            }
            ctx.sync_metadata = {'content_hash': 'h1', 'workflow_version': 'v1'}
            return {}

        def _capture_build(ctx, **kw):
            return ExecuteActionResult(
                payload={
                    'execution': {'action_log_id': 'log-1'},
                    'workflow': ctx.workflow,
                    'pod_cod': {'treasury_pending': False, 'cod_collected': True},
                    'round_trip': {},
                    'sync_metadata': ctx.sync_metadata,
                },
                http_status=201,
            )

        kernel_result = SimpleNamespace(
            action_log=SimpleNamespace(
                log_id='log-1',
                idempotency_key='client-uuid-execute-1',
                operation_action=_collect_payment_action(),
            ),
            reused_existing=False,
        )

        bundle = SimpleNamespace(
            id='pb-1',
            client_payment_id='client-uuid-execute-1',
            shipment_id='ship-1',
            driver_id='drv-1',
            amount=Decimal('100.00'),
            expected_amount=Decimal('100.00'),
            variance_detected=False,
            payment_mode='cash',
            created_at=None,
        )

        class _TreasuryTxn:
            transaction_id = 'tt-1'

        def _kernel_side_effect(context, *, tenant_user, request):
            context.shipment.collection_status = 'Collected'
            return kernel_result

        with patch.object(
            orch._reconcile_service,
            'prepare_pre_execute',
            side_effect=_capture_prepare,
        ), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(
                idempotency_key='client-uuid-execute-1',
                source_ref='',
            ),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
            return_value=None,
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_collect_payment_action(),
        ), patch.object(
            orch,
            '_execute_kernel',
            side_effect=_kernel_side_effect,
        ), patch.object(
            orch._media_service,
            'persist_execution_media',
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            side_effect=_capture_build,
        ), patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'mobile_api.execution.services.execute_action_orchestrator.DriverTreasuryTransaction',
        ) as treasury_txn_model, patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle
            treasury_txn_model.objects.filter.return_value.order_by.return_value.first.return_value = _TreasuryTxn()

            result = orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant-1',
                job_type='shipment',
                job_id='ship-1',
                action_code='A9',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='user-1',
            )

        self.assertIn('payment_bundle', result.payload)
        self.assertEqual(result.payload['payment_bundle']['bundle_id'], 'pb-1')
        self.assertEqual(result.payload['success'], True)
        self.assertEqual(result.payload['action'], 'A9')
        self.assertEqual(result.payload['shipment_id'], 'ship-1')
        self.assertEqual(result.payload['cod_payment_status'], 'Collected')
        self.assertEqual(result.payload['treasury_transaction_id'], 'tt-1')
        self.assertIsNotNone(result.payload['variance'])
        self.assertEqual(result.payload['variance']['has_variance'], False)
        self.assertEqual(result.payload['variance']['variance_type'], 'none')
        self.assertEqual(result.payload['variance']['variance_amount'], '0.00')

    def test_a9_variance_bundle_allowed_and_flagged(self):
        orch = self._orchestrator()

        def _capture_prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.booking = ctx.shipment.booking
            ctx.workflow = {
                'allowed_actions': [{'action_code': 'A9'}],
                'next_action': {'action_code': 'A9'},
                'primary_action': {'action_code': 'A9'},
            }
            ctx.sync_metadata = {'content_hash': 'h1', 'workflow_version': 'v1'}
            return {}

        def _capture_build(ctx, **kw):
            return ExecuteActionResult(
                payload={
                    'execution': {'action_log_id': 'log-1'},
                    'workflow': ctx.workflow,
                    'pod_cod': {'treasury_pending': False, 'cod_collected': True},
                    'round_trip': {},
                    'sync_metadata': ctx.sync_metadata,
                },
                http_status=201,
            )

        kernel_result = SimpleNamespace(
            action_log=SimpleNamespace(
                log_id='log-1',
                idempotency_key='client-uuid-execute-1',
                operation_action=_collect_payment_action(),
            ),
            reused_existing=False,
        )

        bundle = SimpleNamespace(
            id='pb-1',
            client_payment_id='client-uuid-execute-1',
            shipment_id='ship-1',
            driver_id='drv-1',
            amount=Decimal('50.00'),
            expected_amount=Decimal('100.00'),
            variance_detected=True,
            payment_mode='cash',
            created_at=None,
        )

        class _TreasuryTxn:
            transaction_id = 'tt-2'

        def _kernel_side_effect(context, *, tenant_user, request):
            context.shipment.collection_status = 'Collected'
            return kernel_result

        with patch.object(
            orch._reconcile_service,
            'prepare_pre_execute',
            side_effect=_capture_prepare,
        ), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(
                idempotency_key='client-uuid-execute-1',
                source_ref='',
            ),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
            return_value=None,
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_collect_payment_action(),
        ), patch.object(
            orch,
            '_execute_kernel',
            side_effect=_kernel_side_effect,
        ), patch.object(
            orch._media_service,
            'persist_execution_media',
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            side_effect=_capture_build,
        ), patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'mobile_api.execution.services.execute_action_orchestrator.DriverTreasuryTransaction',
        ) as treasury_txn_model, patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle
            treasury_txn_model.objects.filter.return_value.order_by.return_value.first.return_value = _TreasuryTxn()

            result = orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant-1',
                job_type='shipment',
                job_id='ship-1',
                action_code='A9',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='user-1',
            )

        self.assertEqual(result.payload['success'], True)
        self.assertEqual(result.payload['cod_payment_status'], 'Collected')
        self.assertEqual(result.payload['treasury_transaction_id'], 'tt-2')
        self.assertIsNotNone(result.payload['variance'])
        self.assertEqual(result.payload['variance']['has_variance'], True)
        self.assertEqual(result.payload['variance']['variance_type'], 'short')
        self.assertEqual(result.payload['variance']['variance_amount'], '50.00')

    def test_a9_missing_payment_bundle_rejected(self):
        orch = self._orchestrator()

        def _capture_prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.booking = ctx.shipment.booking
            ctx.workflow = {
                'allowed_actions': [{'action_code': 'A9'}],
                'next_action': {'action_code': 'A9'},
                'primary_action': {'action_code': 'A9'},
            }
            ctx.sync_metadata = {'content_hash': 'h1', 'workflow_version': 'v1'}
            return {}

        with patch.object(
            orch._reconcile_service,
            'prepare_pre_execute',
            side_effect=_capture_prepare,
        ), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(
                idempotency_key='client-uuid-execute-1',
                source_ref='',
            ),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
            return_value=None,
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_collect_payment_action(),
        ), patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model:
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = None

            with self.assertRaises(ExecuteActionError) as ctx_exc:
                orch._run_execute_pipeline(
                    driver=_driver(),
                    tenant_schema='tenant-1',
                    job_type='shipment',
                    job_id='ship-1',
                    action_code='A9',
                    payload=self._base_payload(),
                    request=None,
                    tenant_user=None,
                    user_id='user-1',
                )

        self.assertEqual(ctx_exc.exception.code, 'payment_bundle_missing')

    def test_a9_wrong_shipment_payment_bundle_rejected(self):
        orch = self._orchestrator()

        def _capture_prepare(ctx, **kw):
            ctx.shipment = _shipment()
            ctx.booking = ctx.shipment.booking
            ctx.workflow = {
                'allowed_actions': [{'action_code': 'A9'}],
                'next_action': {'action_code': 'A9'},
                'primary_action': {'action_code': 'A9'},
            }
            ctx.sync_metadata = {'content_hash': 'h1', 'workflow_version': 'v1'}
            return {}

        bundle = SimpleNamespace(
            id='pb-1',
            client_payment_id='client-uuid-execute-1',
            shipment_id='ship-other',
            driver_id='drv-1',
            amount=Decimal('100.00'),
            expected_amount=Decimal('100.00'),
            variance_detected=False,
            payment_mode='cash',
            created_at=None,
        )

        with patch.object(
            orch._reconcile_service,
            'prepare_pre_execute',
            side_effect=_capture_prepare,
        ), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(
                idempotency_key='client-uuid-execute-1',
                source_ref='',
            ),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
            return_value=None,
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_collect_payment_action(),
        ), patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle',
        ) as bundle_model, patch(
            'django.db.connection',
            autospec=True,
        ) as db_connection:
            db_connection.schema_name = 'tenant-1'
            bundle_model.objects.filter.return_value.order_by.return_value.first.return_value = bundle

            with self.assertRaises(ExecuteActionError) as ctx_exc:
                orch._run_execute_pipeline(
                    driver=_driver(),
                    tenant_schema='tenant-1',
                    job_type='shipment',
                    job_id='ship-1',
                    action_code='A9',
                    payload=self._base_payload(),
                    request=None,
                    tenant_user=None,
                    user_id='user-1',
                )

        self.assertEqual(ctx_exc.exception.code, 'payment_bundle_shipment_mismatch')

    def test_a9_idempotent_replay_skips_payment_bundle_lookup(self):
        orch = self._orchestrator()

        with patch.object(
            orch._reconcile_service,
            'prepare_pre_execute',
            return_value={},
        ), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(
                idempotency_key='client-uuid-execute-1',
                source_ref='',
            ),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=True,
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            return_value=ExecuteActionResult(payload={'execution': {}}, http_status=200),
        ), patch(
            'mobile_api.payment_collection.models.PaymentCollectionBundle'
        ) as bundle_model:
            bundle_model.objects.filter.side_effect = AssertionError(
                'payment bundle lookup should not run on idempotent replay'
            )

            result = orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant-1',
                job_type='shipment',
                job_id='ship-1',
                action_code='A9',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='user-1',
            )

        self.assertEqual(result.http_status, 200)
        self.assertNotIn('payment_bundle', result.payload)

    def test_movement_execute_success(self):
        orch = self._orchestrator()

        with patch.object(orch._reconcile_service, 'prepare_pre_execute') as prep, patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_action('M1'),
        ), patch.object(
            orch,
            '_execute_kernel',
            return_value=SimpleNamespace(action_log=_action_log(), reused_existing=False),
        ), patch.object(
            orch._media_service,
            'persist_execution_media',
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            return_value=ExecuteActionResult(payload={'execution': {}}, http_status=201),
        ):
            prep.side_effect = lambda ctx, **kw: setattr(ctx, 'movement', _movement()) or {}
            orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant_test',
                job_type='movement',
                job_id='mov-1',
                action_code='M1',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='user-1',
            )
        prep.assert_called_once()

    def test_replay_retry_skips_evidence(self):
        orch = self._orchestrator()
        with patch.object(orch._reconcile_service, 'prepare_pre_execute'), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=True,
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
        ) as mock_evidence, patch.object(
            orch,
            '_execute_kernel',
        ) as mock_kernel, patch.object(
            orch._media_service,
            'persist_execution_media',
        ), patch.object(
            orch._response_service,
            'build_execute_result',
            return_value=ExecuteActionResult(payload={'execution': {}}, http_status=200),
        ):
            result = orch._run_execute_pipeline(
                driver=_driver(),
                tenant_schema='tenant_test',
                job_type='shipment',
                job_id='ship-1',
                action_code='A2',
                payload=self._base_payload(),
                request=None,
                tenant_user=None,
                user_id='user-1',
            )
        mock_evidence.assert_not_called()
        mock_kernel.assert_not_called()
        self.assertEqual(result.http_status, 200)

    def test_stale_rejection_before_kernel(self):
        orch = self._orchestrator()
        with patch.object(orch._reconcile_service, 'prepare_pre_execute'), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            side_effect=ExecuteActionError(
                'stale',
                code='stale_content_hash',
                http_status=409,
                refresh_required=True,
            ),
        ), patch.object(orch, '_execute_kernel') as mock_kernel:
            with self.assertRaises(ExecuteActionError) as exc:
                orch._run_execute_pipeline(
                    driver=_driver(),
                    tenant_schema='tenant_test',
                    job_type='shipment',
                    job_id='ship-1',
                    action_code='A2',
                    payload={
                        **self._base_payload(),
                        'expected_content_hash': 'old',
                    },
                    request=None,
                    tenant_user=None,
                    user_id='user-1',
                )
        self.assertEqual(exc.exception.code, 'stale_content_hash')
        mock_kernel.assert_not_called()

    def test_kernel_validation_maps_to_execute_error(self):
        orch = self._orchestrator()
        with patch.object(orch._reconcile_service, 'prepare_pre_execute'), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_action('A2'),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.ActionExecutionService.execute_driver_action',
            side_effect=DjangoValidationError('POD required'),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.mobile_execution_guard',
        ) as mock_guard:
            @contextmanager
            def _guard_cm(_c):
                yield _c

            mock_guard.side_effect = _guard_cm
            with self.assertRaises(ExecuteActionError) as exc:
                orch._run_execute_pipeline(
                    driver=_driver(),
                    tenant_schema='tenant_test',
                    job_type='shipment',
                    job_id='ship-1',
                    action_code='A2',
                    payload=self._base_payload(),
                    request=None,
                    tenant_user=None,
                    user_id='user-1',
                )
        self.assertEqual(exc.exception.code, 'execution_validation_failed')

    def test_media_failure_prevents_response(self):
        """Media persist failure must abort before post-reconcile response."""
        orch = self._orchestrator()
        with patch.object(orch._reconcile_service, 'prepare_pre_execute'), patch.object(
            orch._idempotency_guard,
            'normalize_request_keys',
            return_value=SimpleNamespace(idempotency_key='k1', source_ref=''),
        ), patch.object(
            orch._idempotency_guard,
            'detect_idempotent_replay',
            return_value=False,
        ), patch.object(
            orch._validation_service,
            'validate_pre_execute_after_idempotency',
            return_value=SimpleNamespace(ok=True, idempotent_replay=False),
        ), patch(
            'mobile_api.execution.services.execute_action_orchestrator.lock_execution_entities',
        ), patch.object(
            orch._evidence_service,
            'validate_required_evidence',
        ), patch.object(
            orch._validation_service,
            'resolve_operation_action',
            return_value=_action('A2'),
        ), patch.object(
            orch,
            '_execute_kernel',
            return_value=SimpleNamespace(action_log=_action_log(), reused_existing=False),
        ), patch.object(
            orch._media_service,
            'persist_execution_media',
            side_effect=RuntimeError('media failed'),
        ), patch.object(
            orch._response_service,
            'build_execute_result',
        ) as mock_response:
            with self.assertRaises(RuntimeError):
                orch._run_execute_pipeline(
                    driver=_driver(),
                    tenant_schema='tenant_test',
                    job_type='shipment',
                    job_id='ship-1',
                    action_code='A2',
                    payload=self._base_payload(),
                    request=None,
                    tenant_user=None,
                    user_id='user-1',
                )
        mock_response.assert_not_called()

    @patch(
        'mobile_api.execution.services.execute_action_orchestrator.mobile_execution_guard',
    )
    @patch(
        'mobile_api.execution.services.execute_action_orchestrator.ActionExecutionService',
    )
    def test_kernel_uses_mobile_channel_and_idempotency(
        self,
        mock_aes,
        mock_guard,
    ):
        orch = self._orchestrator()
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='shipment',
            job_id='ship-1',
            action_code='A2',
            payload={'notes': 'n'},
            shipment=_shipment(),
            operation_action=_action('A2'),
            idempotency_key='key-1',
            source_ref='ref-1',
        )

        @contextmanager
        def _guard_cm(_c):
            yield _c

        mock_guard.side_effect = _guard_cm
        mock_aes.execute_driver_action.return_value = SimpleNamespace(
            action_log=_action_log(),
            reused_existing=False,
        )

        orch._execute_kernel(ctx, tenant_user=SimpleNamespace(pk='tu-1'), request=None)

        mock_aes.execute_driver_action.assert_called_once()
        kwargs = mock_aes.execute_driver_action.call_args.kwargs
        self.assertEqual(kwargs['source_channel'], 'mobile_driver')
        self.assertEqual(kwargs['idempotency_key'], 'key-1')
        self.assertTrue(kwargs['skip_recent_duplicate_guard'])

    def test_cod_action_passes_mobile_cod_amount(self):
        orch = self._orchestrator()
        ctx = ExecuteActionContext(
            driver=_driver(),
            tenant_schema='tenant_test',
            user_id='user-1',
            job_type='shipment',
            job_id='ship-1',
            action_code='A9',
            payload={'mobile_cod_amount': '100.50', 'notes': 'collected'},
            shipment=_shipment(),
            operation_action=_collect_payment_action(),
            idempotency_key='k',
            source_ref='r',
        )
        with patch(
            'mobile_api.execution.services.execute_action_orchestrator.mobile_execution_guard',
        ) as mock_guard, patch(
            'mobile_api.execution.services.execute_action_orchestrator.ActionExecutionService',
        ) as mock_aes:
            @contextmanager
            def _guard_cm(_c):
                yield _c

            mock_guard.side_effect = _guard_cm
            mock_aes.execute_driver_action.return_value = SimpleNamespace(
                action_log=_action_log(),
                reused_existing=False,
            )
            orch._execute_kernel(ctx, tenant_user=None, request=None)
        self.assertEqual(
            mock_aes.execute_driver_action.call_args.kwargs['mobile_cod_amount'],
            '100.50',
        )
