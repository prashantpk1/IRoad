"""Hard POD (A7H) allowed-action policy tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from iroad_tenants.operation_execution import (
    _action_is_allowed,
    _combined_pod_allows_hard_copy_retry,
    _hard_copy_collection_shipment_allowed,
    _is_hard_copy_collection_action,
    _is_standalone_hard_copy_collection_action,
    validate_operation_action_allowed,
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

    def test_combined_pod_not_standalone_hard_copy(self):
        combined = _hard_pod_action()
        combined.action_code = 'OA-0008'
        combined.english_label = 'POD'
        combined.auto_pod_post = True
        self.assertTrue(_is_hard_copy_collection_action(combined))
        self.assertFalse(_is_standalone_hard_copy_collection_action(combined))

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

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    def test_combined_pod_allows_hard_copy_retry_after_digital(
        self,
        _mock_evidence,
        _mock_pending,
    ):
        action = _hard_pod_action()
        action.auto_pod_post = True
        action.action_code = 'OA-0008'
        shipment = SimpleNamespace(pk=uuid4(), pod_type=TenantShipment.PodType.HARD)
        self.assertTrue(_combined_pod_allows_hard_copy_retry(action, shipment))

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': True, 'pod_uploaded': False},
    )
    @patch('iroad_tenants.operation_execution._shipment_has_active_movement', return_value=True)
    @patch('iroad_tenants.operation_execution._executed_action_ids')
    def test_combined_pod_allowed_at_delivered_for_hard_copy_retry(
        self,
        mock_executed_ids,
        _movement,
        _mock_evidence,
        _mock_pending,
    ):
        action = _hard_pod_action()
        action.auto_pod_post = True
        action.action_code = 'OA-0008'
        action.english_label = 'POD'
        action.shipment_status_impact = 'Delivered'
        mock_executed_ids.return_value = {action.action_id}
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.order_type = 'COD'
        self.assertTrue(
            _action_is_allowed(
                action,
                shipment=shipment,
            )
        )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_log_evidence_for_shipment',
        return_value={'hard_pod_log': False, 'pod_uploaded': True},
    )
    @patch('iroad_tenants.operation_execution.get_allowed_actions')
    def test_validate_allows_combined_pod_at_delivered_via_allowed_queryset(
        self,
        mock_allowed,
        _mock_evidence,
        _mock_pending,
    ):
        action = _hard_pod_action()
        action.auto_pod_post = True
        action.action_code = 'OA-0008'
        action.pk = action.action_id
        allowed_qs = MagicMock()
        allowed_qs.filter.return_value.exists.return_value = True
        mock_allowed.return_value = allowed_qs
        shipment = MagicMock()
        shipment.pk = uuid4()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.HARD
        with patch(
            'iroad_tenants.operation_runtime.latest_state.repair_delivered_before_hard_pod_custody',
            return_value=False,
        ):
            self.assertIsNone(
                validate_operation_action_allowed(
                    action,
                    shipment=shipment,
                )
            )

    @patch(
        'mobile_api.dashboard.selectors.pod_cod_policy.derive_hard_pod_pending',
        return_value=True,
    )
    def test_repair_delivered_before_hard_pod_custody(self, _mock_pending):
        from iroad_tenants.operation_runtime.latest_state import (
            repair_delivered_before_hard_pod_custody,
        )

        shipment = MagicMock()
        shipment.shipment_status = TenantShipment.ShipmentStatus.DELIVERED
        shipment.pod_type = TenantShipment.PodType.HARD
        self.assertTrue(repair_delivered_before_hard_pod_custody(shipment))
        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        shipment.save.assert_called_once()
