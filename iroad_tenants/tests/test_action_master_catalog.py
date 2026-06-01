"""Unit tests for production Action Master catalog (no tenant DB required)."""
from __future__ import annotations

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.action_master_catalog import (
    AUTO_COD_VERIFY_ACTION_CODE,
    PRODUCTION_ACTION_MASTER,
)
from iroad_tenants.operation_runtime.impacts import resolve_shipment_status_impact
from tenant_workspace.models import TenantShipment


class ActionMasterCatalogTests(SimpleTestCase):
    def test_catalog_includes_a_pod_verify_with_delivered_impact(self):
        codes = {spec.action_code for spec in PRODUCTION_ACTION_MASTER}
        self.assertIn(AUTO_COD_VERIFY_ACTION_CODE, codes)
        verify = next(
            s for s in PRODUCTION_ACTION_MASTER
            if s.action_code == AUTO_COD_VERIFY_ACTION_CODE
        )
        self.assertEqual(verify.shipment_status_impact, 'Delivered')
        self.assertFalse(verify.mobile_visible)
        self.assertEqual(verify.sequence_number, 75)

    def test_a6_impact_does_not_resolve_to_delivered(self):
        """Guard: At_Delivery must never satisfy Delivered fallback logic."""
        self.assertEqual(
            resolve_shipment_status_impact('At_Delivery'),
            TenantShipment.ShipmentStatus.AT_DELIVERY,
        )
        self.assertEqual(
            resolve_shipment_status_impact('Delivered'),
            TenantShipment.ShipmentStatus.DELIVERED,
        )

    def test_mobile_visible_job_actions_are_a1_through_a10(self):
        mobile_codes = {
            spec.action_code
            for spec in PRODUCTION_ACTION_MASTER
            if spec.mobile_visible and spec.action_scope == 'job'
        }
        self.assertEqual(
            mobile_codes,
            {f'A{i}' for i in range(1, 11)} | {f'EM{i}' for i in range(1, 5)},
        )
