"""Tests for dynamic without-scope Operation Action resolution."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.action_master_catalog import (
    WITHOUT_SCOPE_CANCEL_SHIPMENT_LABEL,
)
from iroad_tenants.operation_runtime.impacts import is_shipment_cancel_action
from iroad_tenants.operation_runtime.latest_state import (
    resolve_effective_shipment_status_for_action,
    sync_shipment_status_from_action_log,
)
from tenant_workspace.models import TenantShipment


class ShipmentCancelImpactTests(SimpleTestCase):
    def test_cancel_shipment_action_resolves_to_cancelled_status(self):
        action = MagicMock()
        action.english_label = WITHOUT_SCOPE_CANCEL_SHIPMENT_LABEL
        action.action_code = 'OA-0021'
        action.shipment_status_impact = ''
        action.auto_pod_post = False

        self.assertTrue(is_shipment_cancel_action(action))
        self.assertEqual(
            resolve_effective_shipment_status_for_action(action=action),
            TenantShipment.ShipmentStatus.CANCELLED,
        )

    def test_sync_does_not_rewind_cancelled_shipment_without_cancel_log(self):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.CANCELLED

        with patch(
            'iroad_tenants.operation_runtime.latest_state.derive_latest_action_status',
            return_value=TenantShipment.ShipmentStatus.AT_DELIVERY,
        ):
            result = sync_shipment_status_from_action_log(shipment)

        self.assertIs(result, shipment)
        self.assertEqual(shipment.shipment_status, TenantShipment.ShipmentStatus.CANCELLED)
        shipment.save.assert_not_called()
