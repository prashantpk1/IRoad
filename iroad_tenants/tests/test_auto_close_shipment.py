"""Auto-close Delivered shipments when POD/COD gates are satisfied."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.side_effects import (
    _apply_auto_close_when_ready,
    _should_auto_close_shipment,
    maybe_auto_close_delivered_shipment,
)
from tenant_workspace.models import TenantShipment


def _cod_shipment(**kwargs):
    shipment = SimpleNamespace(
        pk='sh-1',
        shipment_id='sh-1',
        shipment_status=TenantShipment.ShipmentStatus.DELIVERED,
        order_type='COD',
        collection_status=TenantShipment.CollectionStatus.COLLECTED,
        pod_status=TenantShipment.PodStatus.COMPLIANT,
        pod_type=TenantShipment.PodType.HARD,
        booking=None,
        truck=None,
        driver=None,
        refresh_from_db=MagicMock(),
        save=MagicMock(),
    )
    for key, value in kwargs.items():
        setattr(shipment, key, value)
    return shipment


class AutoCloseShipmentTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    def test_should_auto_close_delivered_cod_with_pod(self, _compliant):
        self.assertTrue(_should_auto_close_shipment(_cod_shipment()))

    def test_should_not_auto_close_in_transit(self):
        shipment = _cod_shipment(
            shipment_status=TenantShipment.ShipmentStatus.IN_TRANSIT,
        )
        self.assertFalse(_should_auto_close_shipment(shipment))

    @patch(
        'iroad_tenants.operation_runtime.latest_state.after_shipment_status_side_effects',
    )
    @patch('iroad_tenants.operation_runtime.side_effects._ensure_auto_close_job_log')
    @patch(
        'iroad_tenants.operation_runtime.side_effects._should_auto_close_shipment',
        return_value=True,
    )
    def test_apply_auto_close_sets_closed(
        self,
        _should,
        _ensure_log,
        _after_effects,
    ):
        shipment = _cod_shipment()
        self.assertTrue(_apply_auto_close_when_ready(shipment))
        self.assertEqual(shipment.shipment_status, TenantShipment.ShipmentStatus.CLOSED)
        shipment.save.assert_called_once()
        _ensure_log.assert_called_once()

    @patch(
        'iroad_tenants.operation_runtime.side_effects._apply_auto_close_when_ready',
        return_value=True,
    )
    def test_maybe_auto_close_delegates(self, mock_apply):
        shipment = _cod_shipment()
        self.assertTrue(maybe_auto_close_delivered_shipment(shipment))
        mock_apply.assert_called_once()

    @patch(
        'iroad_tenants.operation_runtime.side_effects._apply_auto_close_when_ready',
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects.apply_hard_copy_received_if_needed',
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects.apply_hard_copy_pod_type_if_needed',
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._apply_auto_delivered_for_cod',
    )
    @patch(
        'iroad_tenants.services.cod_execution_service.CODExecutionService.apply_collect_payment_side_effect',
    )
    def test_a9_side_effects_do_not_auto_close_job(
        self,
        mock_cod_side_effect,
        mock_auto_delivered,
        _hard_type,
        _hard_received,
        mock_auto_close,
    ):
        from iroad_tenants.operation_runtime.side_effects import apply_execution_side_effects

        action = SimpleNamespace(
            auto_shipment_post=False,
            auto_pod_post=False,
            auto_movement_post=False,
            auto_treasury_post=True,
            shipment_status_impact='',
            movement_status_impact='',
        )
        shipment = _cod_shipment(
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
        action_log = SimpleNamespace(
            operation_action=action,
            booking=None,
            shipment=shipment,
            truck_movement=None,
            log_date=None,
            driver=None,
        )
        with patch(
            'iroad_tenants.operation_runtime.side_effects._is_collect_payment_action',
            return_value=True,
        ):
            apply_execution_side_effects(action_log, created_by_label='driver')
        mock_auto_close.assert_not_called()
