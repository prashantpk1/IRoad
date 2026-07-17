"""End Job must unlock at POD Submitted when Payment Collection is already logged."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from tenant_workspace.models import TenantShipment


class EndJobCodLogGateTests(TestCase):
    def test_payment_collection_label_is_cod_collect_action(self):
        from mobile_api.pod_capture.policy.canonical_pod_action_registry import (
            is_cod_collect_action,
        )

        self.assertTrue(
            is_cod_collect_action(
                SimpleNamespace(
                    action_code='OA-0010',
                    english_label='Payment Collection',
                    auto_treasury_post=False,
                ),
            ),
        )
        self.assertTrue(
            is_cod_collect_action(
                SimpleNamespace(
                    action_code='OA-0099',
                    english_label='Custom COD Step',
                    auto_treasury_post=True,
                ),
            ),
        )

    @patch(
        'iroad_tenants.operation_execution._shipment_payment_collection_logged',
        return_value=True,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    def test_job_close_gate_repairs_cod_from_payment_log(
        self,
        _pod_ok,
        _pay_logged,
    ):
        from iroad_tenants.operation_execution import (
            _shipment_leg_pod_cod_complete_for_job_close,
        )

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            save=MagicMock(),
        )
        self.assertTrue(
            _shipment_leg_pod_cod_complete_for_job_close(shipment),
        )
        self.assertEqual(
            shipment.collection_status,
            TenantShipment.CollectionStatus.COLLECTED,
        )
        shipment.save.assert_called()

    @patch(
        'iroad_tenants.operation_execution._shipment_payment_collection_logged',
        return_value=False,
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    def test_job_close_gate_still_blocks_without_payment(
        self,
        _pod_ok,
        _pay_logged,
    ):
        from iroad_tenants.operation_execution import (
            _shipment_leg_pod_cod_complete_for_job_close,
        )

        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            save=MagicMock(),
        )
        self.assertFalse(
            _shipment_leg_pod_cod_complete_for_job_close(shipment),
        )
        self.assertEqual(
            shipment.collection_status,
            TenantShipment.CollectionStatus.PENDING,
        )
