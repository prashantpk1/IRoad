"""POD upload must not advance COD shipments to Delivered before payment."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError

from iroad_tenants.operation_runtime.latest_state import (
    apply_shipment_status_impact,
    resolve_effective_shipment_status_for_action,
    validate_shipment_status_transition,
)
from tenant_workspace.models import TenantShipment


class PodSubmittedCodGateTests(TestCase):
    def test_resolve_effective_status_remaps_auto_pod_delivered_to_pod_submitted(self):
        action = SimpleNamespace(
            shipment_status_impact='Delivered',
            auto_pod_post=True,
        )
        self.assertEqual(
            resolve_effective_shipment_status_for_action(action=action),
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )

    def test_cod_shipment_rejects_delivered_until_payment(self):
        shipment = SimpleNamespace(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            pod_status=TenantShipment.PodStatus.COMPLETED,
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_shipment_status_transition(
                shipment,
                TenantShipment.ShipmentStatus.DELIVERED,
            )
        self.assertIn('payment is collected', str(ctx.exception))

    @patch(
        'iroad_tenants.operation_runtime.latest_state.after_shipment_status_side_effects',
    )
    def test_misconfigured_pod_action_applies_pod_submitted_for_cod(
        self,
        _mock_after,
    ):
        shipment = SimpleNamespace(
            order_type='COD',
            collection_status=TenantShipment.CollectionStatus.PENDING,
            pod_status=TenantShipment.PodStatus.NOT_COMPLETED,
            shipment_status=TenantShipment.ShipmentStatus.AT_DELIVERY,
            save=lambda update_fields=None: None,
        )
        action = SimpleNamespace(
            shipment_status_impact='Delivered',
            auto_pod_post=True,
        )

        apply_shipment_status_impact(shipment=shipment, action=action)

        self.assertEqual(
            shipment.shipment_status,
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
