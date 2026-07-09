"""Standalone / On Call / without-scope action log execution policy."""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from iroad_tenants.operation_execution import validate_operation_action_allowed
from iroad_tenants.operation_runtime.movement_action_validator import (
    is_on_call_catalog_action,
    is_standalone_execution_action,
)
from tenant_workspace.models import TenantOperationAction


class StandaloneActionExecutionTests(SimpleTestCase):
    def test_is_standalone_execution_action_for_without_and_on_call(self):
        without = SimpleNamespace(action_scope='without', sequence_category='job')
        on_call = SimpleNamespace(action_scope='on_call', sequence_category='job')
        job = SimpleNamespace(action_scope='job', sequence_category='job')
        self.assertTrue(is_standalone_execution_action(without))
        self.assertTrue(is_standalone_execution_action(on_call))
        self.assertFalse(is_standalone_execution_action(job))

    def test_is_on_call_catalog_action(self):
        self.assertTrue(is_on_call_catalog_action(SimpleNamespace(action_scope='on_call')))
        self.assertFalse(is_on_call_catalog_action(SimpleNamespace(action_scope='job')))

    def test_validate_allows_incident_report_for_mobile_standalone_execute(self):
        action = SimpleNamespace(
            pk='oa-17',
            action_id='oa-17',
            status=TenantOperationAction.Status.ACTIVE,
            action_scope='without',
            sequence_category='without',
            english_label='Incident Report',
            action_code='OA-0017',
        )
        shipment = SimpleNamespace(pk='ship-1', shipment_status='In_Transit')
        err = validate_operation_action_allowed(
            action,
            shipment=shipment,
            allow_standalone_execution=True,
        )
        self.assertIsNone(err)
