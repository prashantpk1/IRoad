"""Unit tests for production Action Master catalog (no tenant DB required)."""
from __future__ import annotations

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.action_master_catalog import (
    AUTO_COD_VERIFY_ACTION_CODE,
    AUTO_COD_VERIFY_LOG_NO_PREFIX,
    EMPTY_MOVE_ACTION_CODES,
    PRODUCTION_ACTION_MASTER,
    SYSTEM_AUTO_POD_VERIFY_CHANNELS,
    is_system_auto_pod_verify_channel,
)
from iroad_tenants.operation_runtime.impacts import resolve_shipment_status_impact
from tenant_workspace.models import TenantShipment


class ActionMasterCatalogTests(SimpleTestCase):
    def test_catalog_excludes_backend_only_pod_verify_action(self):
        codes = {spec.action_code for spec in PRODUCTION_ACTION_MASTER}
        self.assertNotIn(AUTO_COD_VERIFY_ACTION_CODE, codes)

    def test_catalog_excludes_without_scope_cancel_actions(self):
        codes = {spec.action_code for spec in PRODUCTION_ACTION_MASTER}
        self.assertFalse(codes & {'R1', 'R2', 'R3', 'R4'})

    def test_catalog_excludes_tenant_defined_extra_actions(self):
        codes = {spec.action_code for spec in PRODUCTION_ACTION_MASTER}
        self.assertFalse(codes & {'A7H', 'EM1', 'EM2', 'EM3', 'EM4'})

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
            {f'A{i}' for i in range(1, 11)},
        )

    def test_legacy_empty_move_codes_not_in_production_catalog(self):
        catalog_codes = {spec.action_code for spec in PRODUCTION_ACTION_MASTER}
        self.assertFalse(catalog_codes & EMPTY_MOVE_ACTION_CODES)

    def test_system_auto_pod_verify_channels_include_cod_and_mobile_close(self):
        self.assertIn('auto_cod_verify', SYSTEM_AUTO_POD_VERIFY_CHANNELS)
        self.assertIn('mobile_job_close_ready', SYSTEM_AUTO_POD_VERIFY_CHANNELS)

    def test_system_auto_pod_verify_log_no_prefix(self):
        self.assertTrue(
            'LOG-POD-VERIFY-9c6619c8-b8de-4de5-a88f-'.startswith(
                AUTO_COD_VERIFY_LOG_NO_PREFIX,
            ),
        )
        self.assertTrue(is_system_auto_pod_verify_channel('auto_cod_verify'))
        self.assertFalse(is_system_auto_pod_verify_channel('mobile'))
