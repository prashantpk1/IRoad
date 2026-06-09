"""Hard POD (A7H) allowed-action policy tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from iroad_tenants.operation_execution import (
    _action_is_allowed,
    _hard_copy_collection_shipment_allowed,
    _is_hard_copy_collection_action,
)
from tenant_workspace.models import TenantOperationAction, TenantShipment


def _hard_pod_action():
    return SimpleNamespace(
        action_id=uuid4(),
        action_code='A7H',
        english_label='Hard POD Collection',
        status=TenantOperationAction.Status.ACTIVE,
        sequence_category='job',
        shipment_status_impact='',
        movement_status_impact='',
        booking_status_impact='',
        auto_shipment_post=False,
        auto_movement_post=False,
        auto_pod_post=False,
        hard_copy_collection=True,
    )


class HardPodAllowedActionTests(TestCase):
    def test_hard_copy_action_detection(self):
        self.assertTrue(_is_hard_copy_collection_action(_hard_pod_action()))

    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value={'A7'})
    def test_hard_copy_allowed_after_a7_at_delivery(self, _mock_codes):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
            order_type='COD',
            booking_item_type='Outbound',
        )
        self.assertTrue(
            _hard_copy_collection_shipment_allowed(shipment),
        )

    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=False)
    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value=set())
    def test_hard_copy_blocked_without_a7_or_custody(self, _mock_codes, _mock_custody):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
        )
        self.assertFalse(_hard_copy_collection_shipment_allowed(shipment))

    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value=set())
    @patch('iroad_tenants.operation_execution._pending_hard_pod_custody_exists', return_value=True)
    def test_hard_copy_allowed_with_pending_custody_submit(self, _mock_custody, _mock_codes):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            pod_type=TenantShipment.PodType.HARD,
        )
        self.assertTrue(_hard_copy_collection_shipment_allowed(shipment))

    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids', return_value=set())
    @patch('iroad_tenants.operation_execution._executed_action_codes', return_value={'A7'})
    def test_action_is_allowed_for_a7h_after_a7(self, _codes, _ids, _movement):
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.AT_DELIVERY
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.order_type = 'COD'
        action = _hard_pod_action()
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
                executed_action_ids=set(),
            )
        )
