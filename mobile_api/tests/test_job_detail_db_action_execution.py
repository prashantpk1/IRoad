"""
PostgreSQL E2E — execute via ActionExecutionService when UI allowed-actions are empty.

Proves transactional log persistence + side effects on the tenant schema using the
first ACTIVE operation action that passes policy (or skips if none).
"""
from __future__ import annotations

import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.test import override_settings

from iroad_tenants.operation_runtime.constants import SOURCE_CHANNEL_MOBILE_DRIVER
from iroad_tenants.services.action_execution_service import ActionExecutionService
from iroad_tenants.services.operation_execution_service import OperationExecutionService
from mobile_api.tests.job_detail_db_support import (
    JobDetailDbTestBase,
    job_detail_db_tests_enabled,
    skip_reason,
)
from tenant_workspace.models import TenantOperationAction, TenantOperationActionLog


@skipUnless(job_detail_db_tests_enabled(), skip_reason())
class JobDetailDirectActionExecutionDbTests(JobDetailDbTestBase):
    """Lower-level execution proofs when DriverJobExecuteService preconditions skip."""

    def _first_policy_allowed_action(self, *, shipment=None, movement=None):
        for action in TenantOperationAction.objects.filter(
            status=TenantOperationAction.Status.ACTIVE,
        ).order_by('sequence_number')[:80]:
            err = OperationExecutionService.validate_driver_action_execution(
                action,
                shipment=shipment,
                movement=movement,
            )
            if err is None:
                return action
        return None

    def test_direct_execute_persists_log_when_policy_allows(self):
        action = self._first_policy_allowed_action(shipment=self.shipment)
        if action is None:
            self.skipTest('No ACTIVE action passes policy for fixture shipment')

        before = self.log_count_for_shipment()
        with self.mobile_execution_guard():
            result = ActionExecutionService.execute_driver_action(
                operation_action=action,
                shipment=self.shipment,
                driver=self.driver,
                tenant_user=self.tenant_user,
                created_by_label='jd-direct-e2e',
                notes='direct-db-e2e',
                source='Mobile',
                source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                idempotency_key=f'jd-direct-{uuid.uuid4().hex}',
            )
        self.assertFalse(result.reused_existing)
        self.assertTrue(
            TenantOperationActionLog.objects.filter(pk=result.action_log.pk).exists()
        )
        self.assertEqual(self.log_count_for_shipment(), before + 1)
        self.shipment.refresh_from_db()

    def test_direct_idempotent_replay(self):
        action = self._first_policy_allowed_action(shipment=self.shipment)
        if action is None:
            self.skipTest('No policy-allowed action')
        key = f'jd-direct-idem-{uuid.uuid4().hex}'
        kw = dict(
            operation_action=action,
            shipment=self.shipment,
            driver=self.driver,
            tenant_user=self.tenant_user,
            source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
            idempotency_key=key,
            notes='direct-idem',
        )
        with self.mobile_execution_guard():
            first = ActionExecutionService.execute_driver_action(**kw)
            second = ActionExecutionService.execute_driver_action(**kw)
        self.assertFalse(first.reused_existing)
        self.assertTrue(second.reused_existing)
        self.assertEqual(first.action_log.pk, second.action_log.pk)

    def test_direct_side_effect_rollback(self):
        action = self._first_policy_allowed_action(shipment=self.shipment)
        if action is None:
            self.skipTest('No policy-allowed action')
        before = self.log_count_for_shipment()
        with patch.object(
            ActionExecutionService,
            'apply_execution_side_effects',
            side_effect=RuntimeError('rollback-e2e'),
        ):
            with self.assertRaises(RuntimeError):
                with self.mobile_execution_guard():
                    ActionExecutionService.execute_driver_action(
                        operation_action=action,
                        shipment=self.shipment,
                        driver=self.driver,
                        tenant_user=self.tenant_user,
                        idempotency_key=f'jd-rb-{uuid.uuid4().hex}',
                        source_channel=SOURCE_CHANNEL_MOBILE_DRIVER,
                    )
        self.assertEqual(self.log_count_for_shipment(), before)

    @override_settings(DEBUG=False, MOBILE_API_JOBS_ENFORCE_ACTION_MEMBERSHIP=True)
    def test_validate_driver_action_execution_matches_allowed_queryset(self):
        action = self._first_policy_allowed_action(shipment=self.shipment)
        if action is None:
            self.skipTest('No policy-allowed action')
        allowed = OperationExecutionService.get_allowed_driver_actions(
            shipment=self.shipment,
        )
        self.assertTrue(allowed.filter(pk=action.pk).exists())
