"""Digital POD bookings must not promote to Hard Copy on POD execute."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from iroad_tenants.operation_field_catalog import operation_shipment_uses_hard_copy_pod
from iroad_tenants.operation_runtime.latest_state import apply_hard_copy_pod_type_if_needed
from tenant_workspace.models import TenantShipment


class DigitalPodHardCopyGateTests(TestCase):
    def test_operation_shipment_uses_hard_copy_respects_digital_booking(self):
        shipment = SimpleNamespace(
            pod_type=TenantShipment.PodType.HARD,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.DIGITAL),
        )
        self.assertFalse(operation_shipment_uses_hard_copy_pod(shipment))

    def test_apply_hard_copy_pod_type_skips_digital_booking(self):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        shipment.booking = SimpleNamespace(pod_type=TenantShipment.PodType.DIGITAL)
        action = SimpleNamespace(hard_copy_collection=True)
        apply_hard_copy_pod_type_if_needed(shipment=shipment, action=action)
        shipment.save.assert_not_called()

    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value={'A7'})
    def test_hard_copy_collection_blocked_for_digital_booking(self, _mock_codes):
        from iroad_tenants.operation_execution import _hard_copy_collection_shipment_allowed

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.DIGITAL),
        )
        self.assertFalse(_hard_copy_collection_shipment_allowed(shipment))
