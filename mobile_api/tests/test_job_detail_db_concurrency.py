"""
PostgreSQL threaded concurrency proofs for Job Detail execution.

Validates under parallel load:
- single Action Log per idempotency key (no duplicate rows)
- idempotent replay (``reused_existing``)
- duplicate-submit guard without extra logs
- ``select_for_update`` row-lock serialization
- safe concurrent timeline reads during writes

Requires dev DB + tenant schema (same env as other Job Detail DB E2E tests):

  $env:MOBILE_API_JOB_DETAIL_TEST_USE_DEV_DB='1'
  python manage.py test mobile_api.tests.test_job_detail_db_concurrency --keepdb
"""
from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.db import transaction
from django.test import override_settings

from mobile_api.services.driver_job_execute_service import DriverJobExecuteService
from mobile_api.services.driver_job_pod_cod_service import DriverJobPodCodService
from mobile_api.services.driver_job_timeline_service import DriverJobTimelineService
from mobile_api.tests.job_detail_concurrency_support import (
    count_logs_with_idempotency_key,
    enrich_execute_body,
    execution_request_for_body,
    run_in_tenant_schema,
    run_parallel,
)
from mobile_api.tests.job_detail_db_support import (
    JobDetailDbTestBase,
    JobDetailRollbackTestMixin,
    job_detail_db_tests_enabled,
    skip_reason,
)
from tenant_workspace.models import TenantOperationActionLog, TenantShipment, TenantShipmentDocument


def _assert_all_success(results: list[dict], errors: list[BaseException]) -> None:
    if errors:
        raise AssertionError(f'worker errors: {errors!r}')
    assert results, 'expected at least one worker result'
    for item in results:
        assert item.get('success'), item


class JobDetailConcurrencyExecuteMixin(JobDetailRollbackTestMixin):
    """Shared execute helpers for threaded Job Detail tests."""

    def _concurrency_shipment_and_action(self):
        """Neutral action (no status impact) so parallel workers can replay safely."""
        shipment = self.fresh_shipment_for_concurrency()
        action = self.ensure_rollback_test_action(
            code_suffix=uuid.uuid4().hex[:6],
        )
        return shipment, action

    def _execute_shipment_body(
        self,
        action,
        *,
        idempotency_key: str = '',
        notes: str = 'concurrency-e2e',
        source_ref: str = '',
    ) -> dict:
        body = {
            'action_id': str(action.action_id),
            'notes': notes,
        }
        if idempotency_key:
            body['idempotency_key'] = idempotency_key
        if source_ref:
            body['source_ref'] = source_ref
        return body

    def _shipment_execute_worker(
        self,
        body: dict,
        *,
        shipment_id: str,
        action,
    ) -> dict:
        payload = enrich_execute_body(body)
        request = execution_request_for_body(payload)

        def _run():
            ctx = self.build_execution_context()
            with self.bypass_execution_policy(action=action):
                return DriverJobExecuteService.execute_shipment_action(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    shipment_id=shipment_id,
                    validated_body=payload,
                    request=request,
                    execution_ctx=ctx,
                )

        return run_in_tenant_schema(self.tenant_schema, _run)

    def _run_parallel_execute(self, workers, *, action=None):
        policy_action = action or self.ensure_rollback_test_action(
            code_suffix='policy',
        )
        with self.bypass_execution_policy(action=policy_action):
            return run_parallel(workers, start_barrier=True, timeout=120.0)


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
@override_settings(DEBUG=True, MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=False)
class JobDetailConcurrentShipmentExecuteTests(
    JobDetailConcurrencyExecuteMixin,
    JobDetailDbTestBase,
):
    """Parallel / double-submit shipment execute-action."""

    WORKER_COUNT = 6

    def test_simultaneous_execute_same_idempotency_single_log(self):
        shipment, action = self._concurrency_shipment_and_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        idem = f'jd-conc-idem-{uuid.uuid4().hex}'
        body = self._execute_shipment_body(action, idempotency_key=idem)
        before = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()

        sid = str(shipment.shipment_id)
        workers = [
            lambda b=body, s=sid, a=action: self._shipment_execute_worker(
                b, shipment_id=s, action=a,
            )
            for _ in range(self.WORKER_COUNT)
        ]
        results, errors = self._run_parallel_execute(workers)

        _assert_all_success(results, errors)
        log_ids = {r['execution']['log_id'] for r in results}
        self.assertEqual(len(log_ids), 1, results)
        self.assertGreaterEqual(
            sum(1 for r in results if r['execution']['reused_existing']),
            self.WORKER_COUNT - 1,
        )
        after = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()
        self.assertEqual(after, before + 1)
        self.assertEqual(
            count_logs_with_idempotency_key(
                idempotency_key=idem,
                shipment_pk=shipment.pk,
            ),
            1,
        )

    def test_idempotency_race_no_duplicate_db_rows(self):
        """DB must never hold two logs with the same idempotency key after a race."""
        shipment, action = self._concurrency_shipment_and_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        idem = f'jd-race-{uuid.uuid4().hex}'
        body = self._execute_shipment_body(action, idempotency_key=idem)
        sid = str(shipment.shipment_id)
        workers = [
            lambda b=body, s=sid, a=action: self._shipment_execute_worker(
                b, shipment_id=s, action=a,
            )
            for _ in range(8)
        ]

        results, errors = self._run_parallel_execute(workers)
        _assert_all_success(results, errors)

        self.assertEqual(
            count_logs_with_idempotency_key(
                idempotency_key=idem,
                shipment_pk=shipment.pk,
            ),
            1,
        )

    def test_rapid_double_submit_without_idempotency_reuses_one_log(self):
        """Duplicate-submit guard: same action + notes within window → one new log."""
        shipment, action = self._concurrency_shipment_and_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        notes = f'jd-dup-{uuid.uuid4().hex[:12]}'
        body = self._execute_shipment_body(action, notes=notes)
        before = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()

        sid = str(shipment.shipment_id)
        workers = [
            lambda b=body, s=sid, a=action: self._shipment_execute_worker(
                b, shipment_id=s, action=a,
            )
            for _ in range(10)
        ]
        results, errors = self._run_parallel_execute(workers)

        _assert_all_success(results, errors)
        after = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()
        self.assertEqual(after, before + 1)
        self.assertTrue(
            sum(1 for r in results if r['execution']['reused_existing']) >= 9,
        )

    def test_parallel_execute_distinct_idempotency_keys_each_add_log(self):
        """Different keys may commit in parallel — each worker owns one new log."""
        shipment, action = self._concurrency_shipment_and_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        before = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()
        bodies = [
            self._execute_shipment_body(
                action,
                idempotency_key=f'jd-par-{uuid.uuid4().hex}',
            )
            for _ in range(4)
        ]
        sid = str(shipment.shipment_id)
        workers = [
            lambda b=body, s=sid, a=action: self._shipment_execute_worker(
                b, shipment_id=s, action=a,
            )
            for body in bodies
        ]
        results, errors = self._run_parallel_execute(workers)

        _assert_all_success(results, errors)
        self.assertFalse(any(r['execution']['reused_existing'] for r in results))
        log_ids = {r['execution']['log_id'] for r in results}
        self.assertEqual(len(log_ids), 4)
        after = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()
        self.assertEqual(after, before + 4)


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailConcurrentMovementExecuteTests(JobDetailDbTestBase):
    def test_simultaneous_movement_execute_idempotency_single_log(self):
        action = self.pick_allowed_movement_action()
        if action is None:
            self.skipTest('No allowed movement action')

        idem = f'jd-mv-conc-{uuid.uuid4().hex}'
        body = {
            'action_id': str(action.action_id),
            'idempotency_key': idem,
            'notes': 'mv-concurrency',
        }
        before = self.log_count_for_movement()
        mid = str(self.movement.movement_id)
        payload = enrich_execute_body(body)
        request = execution_request_for_body(payload)

        def _worker():
            def _run():
                ctx = self.build_execution_context()
                return DriverJobExecuteService.execute_movement_action(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    movement_id=mid,
                    validated_body=payload,
                    request=request,
                    execution_ctx=ctx,
                )

            return run_in_tenant_schema(self.tenant_schema, _run)

        workers = [_worker for _ in range(6)]
        results, errors = run_parallel(workers, start_barrier=True, timeout=120.0)

        _assert_all_success(results, errors)
        self.assertEqual(len({r['execution']['log_id'] for r in results}), 1)
        self.assertEqual(self.log_count_for_movement(), before + 1)
        self.assertEqual(
            count_logs_with_idempotency_key(
                idempotency_key=idem,
                movement_pk=self.movement.pk,
            ),
            1,
        )


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
@override_settings(DEBUG=True, MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=False)
class JobDetailRowLockContentionTests(
    JobDetailConcurrencyExecuteMixin,
    JobDetailDbTestBase,
):
    def test_select_for_update_blocks_second_session_until_release(self):
        from mobile_api.helpers.job_detail_perf import lock_entities_for_execution

        acquired = threading.Event()
        release = threading.Event()
        wait_elapsed: list[float] = []
        holder_error: list[BaseException] = []

        def _holder():
            try:
                def _run():
                    with transaction.atomic():
                        lock_entities_for_execution(shipment=self.shipment)
                        acquired.set()
                        release.wait(timeout=15.0)

                run_in_tenant_schema(self.tenant_schema, _run)
            except BaseException as exc:
                holder_error.append(exc)
            finally:
                release.set()

        def _waiter():
            acquired.wait(timeout=10.0)

            def _run():
                with transaction.atomic():
                    t0 = time.perf_counter()
                    lock_entities_for_execution(shipment=self.shipment)
                    wait_elapsed.append(time.perf_counter() - t0)

            run_in_tenant_schema(self.tenant_schema, _run)

        t_holder = threading.Thread(target=_holder)
        t_waiter = threading.Thread(target=_waiter)
        t_holder.start()
        t_waiter.start()
        t_holder.join(timeout=20.0)
        t_waiter.join(timeout=20.0)
        release.set()

        self.assertFalse(holder_error, holder_error)
        self.assertTrue(acquired.is_set())
        self.assertEqual(len(wait_elapsed), 1)
        self.assertGreaterEqual(
            wait_elapsed[0],
            0.05,
            'second session should block on row lock until holder commits',
        )

    def test_concurrent_execute_serializes_via_transaction_and_lock(self):
        """Without idempotency, parallel executes still yield one log (duplicate guard)."""
        shipment, action = self._concurrency_shipment_and_action()
        body = {
            'action_id': str(action.action_id),
            'notes': f'jd-lock-ser-{uuid.uuid4().hex} concurrency serialization',
        }
        before = TenantOperationActionLog.objects.filter(shipment_id=shipment.pk).count()
        sid = str(shipment.shipment_id)
        workers = [
            lambda b=body, s=sid, a=action: self._shipment_execute_worker(
                b, shipment_id=s, action=a,
            )
            for _ in range(5)
        ]

        results, errors = self._run_parallel_execute(workers, action=action)
        _assert_all_success(results, errors)
        after = TenantOperationActionLog.objects.filter(shipment_id=shipment.pk).count()
        self.assertEqual(after, before + 1)


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailConcurrentPodCodTests(JobDetailDbTestBase):
    def _cod_shipment(self):
        return TenantShipment.objects.create(
            shipment_id=uuid.uuid4(),
            shipment_no=f'JD-CCOD-{uuid.uuid4().hex[:8]}',
            booking_item_ref='JD-CCOD',
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
            order_type='COD',
            cod_amount=Decimal('99.00'),
            collection_status=TenantShipment.CollectionStatus.PENDING,
            driver=self.driver,
        )

    def test_parallel_pod_upload_same_idempotency_single_log(self):
        from mobile_api.helpers.compliance_operation_actions import resolve_pod_upload_action

        if resolve_pod_upload_action() is None:
            self.skipTest('POD action (A7) not configured')

        TenantShipmentDocument.objects.create(
            shipment=self.shipment,
            record_no=f'DN-{uuid.uuid4().hex[:8]}',
            document_type='delivery_note',
            document_ref_no=f'DNREF-{uuid.uuid4().hex[:8]}',
            is_delivery_note=True,
            status=TenantShipmentDocument.Status.PENDING,
        )
        idem = f'jd-pod-par-{uuid.uuid4().hex}'
        before = self.log_count_for_shipment()
        sid = str(self.shipment.shipment_id)

        pod_body = enrich_execute_body({
            'idempotency_key': idem,
            'notes': 'pod-parallel-upload',
        })
        pod_request = execution_request_for_body(pod_body)

        def _worker():
            def _run():
                ctx = self.build_execution_context()
                with patch(
                    'mobile_api.helpers.action_execution_validation.count_media_attachments',
                    return_value=2,
                ):
                    return DriverJobPodCodService.upload_pod(
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        shipment_id=sid,
                        validated_body=pod_body,
                        request=pod_request,
                        execution_ctx=ctx,
                    )

            return run_in_tenant_schema(self.tenant_schema, _run)

        results, errors = run_parallel(
            [_worker for _ in range(5)],
            start_barrier=True,
            timeout=120.0,
        )
        if errors:
            raise AssertionError(errors)
        for item in results:
            if not item.get('success') and item.get('code') in (
                'action_not_allowed',
                'pod_validation_failed',
            ):
                self.skipTest(f'POD not allowed: {item}')
        _assert_all_success(results, errors)
        self.assertEqual(len({r['execution']['log_id'] for r in results}), 1)
        self.assertEqual(self.log_count_for_shipment(), before + 1)
        self.assertEqual(
            count_logs_with_idempotency_key(
                idempotency_key=idem,
                shipment_pk=self.shipment.pk,
            ),
            1,
        )

    def test_parallel_cod_collect_same_idempotency_single_log(self):
        from mobile_api.helpers.compliance_operation_actions import resolve_cod_collect_action

        if resolve_cod_collect_action() is None:
            self.skipTest('COD action (A9) not configured')

        shipment = self._cod_shipment()
        idem = f'jd-cod-par-{uuid.uuid4().hex}'
        before = TenantOperationActionLog.objects.filter(
            shipment_id=shipment.pk,
        ).count()
        sid = str(shipment.shipment_id)

        cod_body = enrich_execute_body({
            'idempotency_key': idem,
            'cod_amount': '99.00',
            'notes': 'cod-parallel-collect',
        })
        cod_request = execution_request_for_body(cod_body)

        def _worker():
            def _run():
                ctx = self.build_execution_context()
                return DriverJobPodCodService.collect_cod(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    shipment_id=sid,
                    validated_body=cod_body,
                    request=cod_request,
                    execution_ctx=ctx,
                )

            return run_in_tenant_schema(self.tenant_schema, _run)

        results, errors = run_parallel(
            [_worker for _ in range(5)],
            start_barrier=True,
            timeout=120.0,
        )
        if errors:
            raise AssertionError(errors)
        for item in results:
            if not item.get('success') and item.get('code') in (
                'action_not_allowed',
                'cod_validation_failed',
            ):
                self.skipTest(f'COD not allowed: {item}')
        _assert_all_success(results, errors)
        self.assertEqual(len({r['execution']['log_id'] for r in results}), 1)
        after = TenantOperationActionLog.objects.filter(shipment_id=shipment.pk).count()
        self.assertEqual(after, before + 1)
        self.assertEqual(
            count_logs_with_idempotency_key(
                idempotency_key=idem,
                shipment_pk=shipment.pk,
            ),
            1,
        )


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailConcurrentTimelineTests(JobDetailDbTestBase):
    def test_concurrent_timeline_reads_during_execute(self):
        action = self.pick_allowed_shipment_action()
        if action is None:
            self.skipTest('No allowed shipment action')

        self.create_action_logs(count=3)
        baseline = self.timeline_log_count_shipment()
        idem = f'jd-tl-conc-{uuid.uuid4().hex}'
        request = self.make_timeline_request(page_size='20')

        read_counts: list[int] = []
        read_errors: list[BaseException] = []
        write_result: list[dict] = []

        def _read_timeline():
            try:
                def _run():
                    out = DriverJobTimelineService.get_shipment_timeline(
                        driver=self.driver,
                        shipment_id=str(self.shipment.shipment_id),
                        request=request,
                    )
                    if not out.get('success'):
                        raise AssertionError(out)
                    return len(out['timeline']['items'])

                count = run_in_tenant_schema(self.tenant_schema, _run)
                read_counts.append(count)
            except BaseException as exc:
                read_errors.append(exc)

        write_body = enrich_execute_body({
            'action_id': str(action.action_id),
            'idempotency_key': idem,
            'notes': f'tl-concurrent-write-{uuid.uuid4().hex}',
        })
        write_request = execution_request_for_body(write_body)
        write_sid = str(self.shipment.shipment_id)

        def _execute_once():
            def _run():
                write_ctx = self.build_execution_context()
                return DriverJobExecuteService.execute_shipment_action(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    shipment_id=write_sid,
                    validated_body=write_body,
                    request=write_request,
                    execution_ctx=write_ctx,
                )

            write_result.append(run_in_tenant_schema(self.tenant_schema, _run))

        workers = [_read_timeline for _ in range(8)] + [_execute_once]
        _, errors = run_parallel(workers, start_barrier=True, timeout=120.0)

        self.assertFalse(read_errors, read_errors)
        self.assertFalse(errors, errors)
        self.assertEqual(len(read_counts), 8)
        self.assertTrue(read_counts)
        for count in read_counts:
            self.assertGreaterEqual(count, 1)
            self.assertLessEqual(count, baseline + 1)

        self.assertEqual(len(write_result), 1)
        self.assertTrue(write_result[0].get('success'), write_result[0])
        self.assertGreaterEqual(self.timeline_log_count_shipment(), baseline)
