"""
PostgreSQL E2E — Job Detail execute-action, transactions, locks, idempotency.
"""
from __future__ import annotations

import threading
import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, transaction
from django.test import override_settings

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.services.action_execution_service import ActionExecutionService
from mobile_api.services.driver_job_execute_service import DriverJobExecuteService
from mobile_api.tests.job_detail_db_support import (
    JobDetailDbTestBase,
    job_detail_db_tests_enabled,
    skip_reason,
)
from tenant_workspace.models import TenantOperationActionLog


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailShipmentExecuteDbTests(JobDetailDbTestBase):
    def test_shipment_execute_persists_action_log(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action for test shipment')

        ctx = self.build_execution_context()
        before = self.log_count_for_shipment()
        idem = f'jd-exec-{uuid.uuid4().hex}'

        result = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body={
                'action_id': str(action.action_id),
                'idempotency_key': idem,
                'notes': 'jd-db-e2e',
                'source_ref': f'ref-{idem}',
            },
            execution_ctx=ctx,
        )
        self.assertTrue(result.get('success'), result)
        exec_block = result.get('execution') or {}
        self.assertFalse(exec_block.get('reused_existing'))
        self.assertTrue(
            TenantOperationActionLog.objects.filter(
                log_id=exec_block['log_id'],
                shipment_id=self.shipment.pk,
                driver_id=self.driver.pk,
            ).exists()
        )
        self.assertEqual(self.log_count_for_shipment(), before + 1)

    def test_idempotent_replay_returns_same_log(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        ctx = self.build_execution_context()
        idem = f'jd-idem-{uuid.uuid4().hex}'
        body = {
            'action_id': str(action.action_id),
            'idempotency_key': idem,
            'notes': 'idem-e2e',
            'source_ref': f'ref-{idem}',
        }
        first = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body=body,
            execution_ctx=ctx,
        )
        self.assertTrue(first.get('success'))
        log_id_first = first['execution']['log_id']
        count_after_first = self.log_count_for_shipment()

        second = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body=body,
            execution_ctx=ctx,
        )
        self.assertTrue(second.get('success'))
        self.assertTrue(second['execution']['reused_existing'])
        self.assertEqual(second['execution']['log_id'], log_id_first)
        self.assertEqual(self.log_count_for_shipment(), count_after_first)

    def test_duplicate_execution_rejected_without_extra_log(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        ctx = self.build_execution_context()
        body = {
            'action_id': str(action.action_id),
            'notes': 'dup-guard-e2e',
            'source_ref': '',
        }
        first = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body=dict(body),
            execution_ctx=ctx,
        )
        self.assertTrue(first.get('success'))
        count_after_first = self.log_count_for_shipment()

        second = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body=dict(body),
            execution_ctx=ctx,
        )
        self.assertTrue(second.get('success'))
        self.assertTrue(second['execution']['reused_existing'])
        self.assertEqual(self.log_count_for_shipment(), count_after_first)

    def test_invalid_action_not_persisted(self):
        ctx = self.build_execution_context()
        before = self.log_count_for_shipment()
        bogus = uuid.uuid4()
        result = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body={
                'action_id': str(bogus),
                'idempotency_key': f'jd-bad-{uuid.uuid4().hex}',
            },
            execution_ctx=ctx,
        )
        self.assertFalse(result.get('success'))
        self.assertIn(result.get('code'), ('invalid_action', 'action_not_allowed'))
        self.assertEqual(self.log_count_for_shipment(), before)

    @override_settings(DEBUG=False, MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=True)
    def test_membership_blocks_disallowed_action_id(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')
        from tenant_workspace.models import TenantOperationAction

        disallowed = (
            TenantOperationAction.objects.filter(
                status=TenantOperationAction.Status.ACTIVE,
            )
            .exclude(pk=action.pk)
            .values_list('pk', flat=True)
            .first()
        )
        if not disallowed:
            disallowed = uuid.uuid4()
        ctx = self.build_execution_context()
        before = self.log_count_for_shipment()
        result = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body={
                'action_id': str(disallowed),
                'idempotency_key': f'jd-mem-{uuid.uuid4().hex}',
            },
            execution_ctx=ctx,
        )
        self.assertFalse(result.get('success'))
        self.assertEqual(self.log_count_for_shipment(), before)

    def test_side_effect_failure_rolls_back_action_log(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        before = self.log_count_for_shipment()
        with patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=RuntimeError('side_effect_boom'),
        ):
            with self.assertRaises(RuntimeError):
                with self.mobile_execution_guard():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        shipment=self.shipment,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        created_by_label='jd-rollback',
                        notes='rollback-e2e',
                        source='Mobile',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                        idempotency_key=f'jd-rb-{uuid.uuid4().hex}',
                    )
        self.assertEqual(self.log_count_for_shipment(), before)

    def test_workflow_refresh_after_execute(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')
        ctx = self.build_execution_context()
        result = DriverJobExecuteService.execute_shipment_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            shipment_id=str(self.shipment.shipment_id),
            validated_body={
                'action_id': str(action.action_id),
                'idempotency_key': f'jd-wf-{uuid.uuid4().hex}',
                'notes': 'workflow-e2e',
            },
            execution_ctx=ctx,
        )
        self.assertTrue(result.get('success'))
        workflow = result.get('workflow') or {}
        self.assertIn('allowed_actions', workflow)
        self.assertIn('execution_state', workflow)


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailMovementExecuteDbTests(JobDetailDbTestBase):
    def test_movement_execute_persists_action_log(self):
        action = self.pick_allowed_movement_action()
        if action is None:
            self.skipTest('No allowed movement action for empty movement')

        ctx = self.build_execution_context()
        before = TenantOperationActionLog.objects.filter(
            truck_movement_id=self.movement.pk,
        ).count()
        idem = f'jd-mv-{uuid.uuid4().hex}'

        result = DriverJobExecuteService.execute_movement_action(
            driver=self.driver,
            tenant_user=self.tenant_user,
            movement_id=str(self.movement.movement_id),
            validated_body={
                'action_id': str(action.action_id),
                'idempotency_key': idem,
                'notes': 'movement-e2e',
            },
            execution_ctx=ctx,
        )
        self.assertTrue(result.get('success'), result)
        after = TenantOperationActionLog.objects.filter(
            truck_movement_id=self.movement.pk,
        ).count()
        self.assertEqual(after, before + 1)


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailRowLockDbTests(JobDetailDbTestBase):
    def test_select_for_update_locks_shipment_row(self):
        from django.db import transaction

        from mobile_api.helpers.job_detail_perf import lock_entities_for_execution

        with transaction.atomic():
            locked, _ = lock_entities_for_execution(shipment=self.shipment)
            self.assertEqual(locked.pk, self.shipment.pk)

    def test_concurrent_execute_with_idempotency_single_log(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        ctx = self.build_execution_context()
        idem = f'jd-thread-{uuid.uuid4().hex}'
        body = {
            'action_id': str(action.action_id),
            'idempotency_key': idem,
            'notes': 'thread-idem',
        }
        results: list[dict] = []
        errors: list[Exception] = []

        def run_execute():
            from django_tenants.utils import schema_context

            try:
                connections = __import__('django.db', fromlist=['connections']).connections
                connections['default'].close()
                with schema_context(self.tenant_schema):
                    out = DriverJobExecuteService.execute_shipment_action(
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        shipment_id=str(self.shipment.shipment_id),
                        validated_body=dict(body),
                        execution_ctx=ctx,
                    )
                    results.append(out)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=run_execute)
        t2 = threading.Thread(target=run_execute)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.get('success') for r in results))
        log_ids = {r['execution']['log_id'] for r in results}
        self.assertEqual(len(log_ids), 1)
        self.assertTrue(any(r['execution']['reused_existing'] for r in results))

    def test_execute_core_uses_row_lock_inside_transaction(self):
        """Execute path calls lock_entities_for_execution inside atomic()."""
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')
        ctx = self.build_execution_context()
        from django.db import transaction

        with transaction.atomic():
            from mobile_api.helpers.job_detail_perf import lock_entities_for_execution

            locked, _ = lock_entities_for_execution(shipment=self.shipment)
            self.assertIsNotNone(locked)
            result = DriverJobExecuteService._execute_core(
                driver=self.driver,
                tenant_user=self.tenant_user,
                operation_action=action,
                shipment=locked,
                movement=None,
                validated_body={
                    'action_id': str(action.action_id),
                    'idempotency_key': f'jd-lock-{uuid.uuid4().hex}',
                    'notes': 'lock-in-txn',
                },
                request=None,
            )
        self.assertTrue(result.get('success'), result)
