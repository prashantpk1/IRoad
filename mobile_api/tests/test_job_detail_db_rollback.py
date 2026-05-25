"""
PostgreSQL E2E — Job Detail transaction rollback and atomicity proofs.

Proves that when execution fails (side effects, media, IntegrityError, POD/COD),
no Action Log, media, timeline row, or shipment/movement status change persists.
"""
from __future__ import annotations

import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.db import IntegrityError, transaction

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.services.action_execution_service import ActionExecutionService
from mobile_api.services.driver_job_execute_service import DriverJobExecuteService
from mobile_api.services.driver_job_pod_cod_service import DriverJobPodCodService
from mobile_api.services.driver_job_timeline_service import DriverJobTimelineService
from mobile_api.tests.job_detail_db_support import (
    JobDetailDbTestBase,
    JobDetailRollbackTestMixin,
    job_detail_db_tests_enabled,
    skip_reason,
)
from tenant_workspace.models import TenantOperationActionLog, TenantShipment


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailActionLogRollbackDbTests(JobDetailRollbackTestMixin, JobDetailDbTestBase):
    """ActionExecutionService + DriverJobExecuteService atomic rollback."""

    def test_side_effect_exception_rolls_back_action_log_direct(self):
        action = self.ensure_rollback_test_action()
        before = self.capture_rollback_snapshot()

        with patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=RuntimeError('side_effect_failed'),
        ):
            with self.assertRaises(RuntimeError):
                with self.mobile_execution_guard():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        shipment=self.shipment,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        idempotency_key=f'jd-rb-se-{uuid.uuid4().hex}',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    )

        self.assert_rollback_snapshot(before, msg='direct side_effect')

    def test_integrity_error_on_save_rolls_back_action_log(self):
        action = self.ensure_rollback_test_action()
        before = self.capture_rollback_snapshot()
        original_save = TenantOperationActionLog.save

        def failing_save(self_row, *args, **kwargs):
            if kwargs.get('force_insert') or not self_row._state.adding:
                return original_save(self_row, *args, **kwargs)
            raise IntegrityError('simulated_unique_violation')

        with patch.object(TenantOperationActionLog, 'save', failing_save):
            with self.assertRaises(IntegrityError):
                with self.mobile_execution_guard():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        shipment=self.shipment,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        idempotency_key=f'jd-rb-ie-{uuid.uuid4().hex}',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    )

        self.assert_rollback_snapshot(before, msg='IntegrityError on save')

    def test_nested_atomic_side_effect_failure_outer_execute_service(self):
        action = self.ensure_rollback_test_action()
        ctx = self.build_execution_context()
        before = self.capture_rollback_snapshot()

        with self.bypass_execution_policy(action=action), patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=RuntimeError('nested_atomic_fail'),
        ):
            with self.assertRaises(RuntimeError):
                DriverJobExecuteService.execute_shipment_action(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    shipment_id=str(self.shipment.shipment_id),
                    validated_body={
                        'action_id': str(action.action_id),
                        'idempotency_key': f'jd-rb-nest-{uuid.uuid4().hex}',
                        'notes': 'nested-fail',
                    },
                    execution_ctx=ctx,
                )

        self.assert_rollback_snapshot(before, msg='nested execute_shipment_action')

    def test_media_save_failure_rolls_back_log_and_timeline(self):
        action = self.ensure_rollback_test_action()
        ctx = self.build_execution_context()
        before = self.capture_rollback_snapshot()
        request = self.make_execute_request_with_media()

        with self.bypass_execution_policy(action=action), patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
        ), patch(
            'mobile_api.services.driver_job_execute_service.save_action_log_media_from_mobile_request',
            side_effect=RuntimeError('media_persist_failed'),
        ), self.assertRaises(RuntimeError):
                DriverJobExecuteService.execute_shipment_action(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    shipment_id=str(self.shipment.shipment_id),
                    validated_body={
                        'action_id': str(action.action_id),
                        'idempotency_key': f'jd-rb-media-{uuid.uuid4().hex}',
                    },
                    request=request,
                    execution_ctx=ctx,
                )

        self.assert_rollback_snapshot(before, msg='media failure')

    def test_timeline_unchanged_after_failed_execute(self):
        action = self.ensure_rollback_test_action()
        ctx = self.build_execution_context()
        self.create_action_logs(count=2, action=action)
        before = self.capture_rollback_snapshot()

        timeline_before = DriverJobTimelineService.get_shipment_timeline(
            driver=self.driver,
            shipment_id=str(self.shipment.shipment_id),
            request=self.make_timeline_request(page_size='10'),
        )
        self.assertTrue(timeline_before.get('success'))
        count_items_before = len(timeline_before['timeline']['items'])

        with self.bypass_execution_policy(action=action), patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=RuntimeError('timeline_rollback'),
        ):
            with self.assertRaises(RuntimeError):
                DriverJobExecuteService.execute_shipment_action(
                    driver=self.driver,
                    tenant_user=self.tenant_user,
                    shipment_id=str(self.shipment.shipment_id),
                    validated_body={
                        'action_id': str(action.action_id),
                        'idempotency_key': f'jd-rb-tl-{uuid.uuid4().hex}',
                    },
                    execution_ctx=ctx,
                )

        self.assert_rollback_snapshot(before, msg='timeline rollback')
        timeline_after = DriverJobTimelineService.get_shipment_timeline(
            driver=self.driver,
            shipment_id=str(self.shipment.shipment_id),
            request=self.make_timeline_request(page_size='10'),
        )
        self.assertEqual(
            len(timeline_after['timeline']['items']),
            count_items_before,
            'timeline item count increased after failed execute',
        )


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailEntityStatusRollbackDbTests(JobDetailRollbackTestMixin, JobDetailDbTestBase):
    """Shipment / movement column updates roll back with failed side effects."""

    def test_shipment_status_rollback_when_side_effect_aborts(self):
        action = self.ensure_status_impact_action(
            shipment_impact=TenantShipment.ShipmentStatus.IN_TRANSIT,
        )
        before = self.capture_rollback_snapshot()
        self.assertNotEqual(before.shipment_status, TenantShipment.ShipmentStatus.IN_TRANSIT)

        def mutate_then_fail(action_log, *, created_by_label=''):
            if action_log.shipment_id:
                TenantShipment.objects.filter(pk=action_log.shipment_id).update(
                    shipment_status=TenantShipment.ShipmentStatus.IN_TRANSIT,
                )
            raise RuntimeError('abort_after_status_touch')

        with patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=mutate_then_fail,
        ):
            with self.assertRaises(RuntimeError):
                with self.mobile_execution_guard():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        shipment=self.shipment,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        idempotency_key=f'jd-rb-shp-{uuid.uuid4().hex}',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    )

        self.assert_rollback_snapshot(before, msg='shipment status')

    def test_movement_status_rollback_when_side_effect_aborts(self):
        from tenant_workspace.models import TenantTruckMovementLog

        action = self.ensure_status_impact_action(
            movement_impact=TenantTruckMovementLog.Status.IN_PROGRESS,
        )
        before = self.capture_rollback_snapshot()

        def mutate_then_fail(action_log, *, created_by_label=''):
            if action_log.truck_movement_id:
                TenantTruckMovementLog.objects.filter(
                    pk=action_log.truck_movement_id,
                ).update(status=TenantTruckMovementLog.Status.IN_PROGRESS)
            raise RuntimeError('abort_after_movement_touch')

        with patch.object(
            ActionExecutionService,
            'validate_driver_action_execution',
            return_value=None,
        ), patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=mutate_then_fail,
        ):
            with self.assertRaises(RuntimeError):
                with self.mobile_execution_guard():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        movement=self.movement,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        idempotency_key=f'jd-rb-mv-{uuid.uuid4().hex}',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    )

        self.assert_rollback_snapshot(before, msg='movement status')


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailPodCodRollbackDbTests(JobDetailRollbackTestMixin, JobDetailDbTestBase):
    """POD / COD service atomic boundaries roll back on execute failure."""

    def test_pod_execute_failure_rolls_back_action_log(self):
        from mobile_api.helpers.compliance_operation_actions import resolve_pod_upload_action

        pod_action = resolve_pod_upload_action()
        if pod_action is None:
            pod_action = self.ensure_rollback_test_action(code_suffix='pod')

        ctx = self.build_execution_context()
        before = self.capture_rollback_snapshot()

        with patch(
            'mobile_api.services.driver_job_pod_cod_service.resolve_pod_upload_action',
            return_value=pod_action,
        ), patch(
            'mobile_api.services.driver_job_pod_cod_service.validate_pod_upload_compliance',
        ), patch(
            'mobile_api.services.driver_job_pod_cod_service.fetch_active_movement',
            return_value=None,
        ), patch(
            'mobile_api.helpers.job_execution_security.authorize_driver_action_execution',
            return_value={'success': True},
        ), patch.object(
            DriverJobExecuteService,
            '_execute_core',
            side_effect=RuntimeError('pod_execute_core_failed'),
        ), self.assertRaises(RuntimeError):
            DriverJobPodCodService.upload_pod(
                driver=self.driver,
                tenant_user=self.tenant_user,
                shipment_id=str(self.shipment.shipment_id),
                validated_body={'idempotency_key': f'jd-rb-pod-{uuid.uuid4().hex}'},
                execution_ctx=ctx,
            )

        self.assert_rollback_snapshot(before, msg='POD failure')

    def test_cod_collect_failure_rolls_back_action_log(self):
        from mobile_api.helpers.compliance_operation_actions import resolve_cod_collect_action

        cod_shipment = TenantShipment.objects.create(
            shipment_id=uuid.uuid4(),
            shipment_no=f'JD-COD-RB-{uuid.uuid4().hex[:8]}',
            booking_item_ref='JD-COD-RB',
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            sourcing_mode=TenantShipment.SourcingMode.IN_SOURCE,
            order_type='COD',
            cod_amount='100.00',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            driver=self.driver,
        )
        cod_action = resolve_cod_collect_action() or self.ensure_rollback_test_action(
            code_suffix='cod',
        )
        ctx = self.build_execution_context()
        before = self.capture_rollback_snapshot()

        with patch(
            'mobile_api.services.driver_job_pod_cod_service.resolve_cod_collect_action',
            return_value=cod_action,
        ), patch(
            'mobile_api.services.driver_job_pod_cod_service.validate_cod_collection_compliance',
            return_value=cod_shipment.cod_amount,
        ), patch(
            'mobile_api.services.driver_job_pod_cod_service.fetch_active_movement',
            return_value=None,
        ), patch(
            'mobile_api.helpers.job_execution_security.authorize_driver_action_execution',
            return_value={'success': True},
        ), patch.object(
            DriverJobExecuteService,
            '_execute_core',
            side_effect=RuntimeError('cod_execute_core_failed'),
        ), self.assertRaises(RuntimeError):
            DriverJobPodCodService.collect_cod(
                driver=self.driver,
                tenant_user=self.tenant_user,
                shipment_id=str(cod_shipment.shipment_id),
                validated_body={
                    'idempotency_key': f'jd-rb-cod-{uuid.uuid4().hex}',
                    'cod_amount': '100.00',
                },
                execution_ctx=ctx,
            )

        self.assert_rollback_snapshot(before, msg='COD failure')
        self.assertEqual(
            TenantOperationActionLog.objects.filter(shipment_id=cod_shipment.pk).count(),
            0,
        )

    def test_transaction_abort_explicit_atomic_block(self):
        """Explicit transaction.atomic() abort matches execute rollback semantics."""
        action = self.ensure_rollback_test_action()
        before = self.capture_rollback_snapshot()

        with self.assertRaises(RuntimeError):
            with self.mobile_execution_guard():
                with transaction.atomic():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        shipment=self.shipment,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        idempotency_key=f'jd-rb-abort-{uuid.uuid4().hex}',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    )
                    raise RuntimeError('explicit_transaction_abort')

        self.assert_rollback_snapshot(before, msg='explicit atomic abort')
