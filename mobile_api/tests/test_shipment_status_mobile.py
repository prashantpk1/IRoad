"""Mobile shipment status: Hard POD defers POD Submitted until custody completes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from mobile_api.helpers.shipment_status_mobile import mobile_effective_shipment_status
from tenant_workspace.models import TenantShipment


class MobileEffectiveShipmentStatusTests(TestCase):
    @patch(
        'mobile_api.helpers.shipment_status_mobile.clamp_shipment_status_cache_for_hard_pod',
        return_value=TenantShipment.ShipmentStatus.AT_DELIVERY,
    )
    def test_clamps_premature_pod_submitted_for_hard_pod(self, _clamp):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            pod_type=TenantShipment.PodType.HARD,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.HARD),
        )
        self.assertEqual(
            mobile_effective_shipment_status(
                shipment,
                TenantShipment.ShipmentStatus.POD_SUBMITTED,
            ),
            TenantShipment.ShipmentStatus.AT_DELIVERY,
        )

    @patch(
        'mobile_api.helpers.shipment_status_mobile.clamp_shipment_status_cache_for_hard_pod',
        side_effect=lambda _s, status: status,
    )
    def test_digital_pod_submitted_unchanged(self, _clamp):
        shipment = SimpleNamespace(
            pk=uuid4(),
            shipment_status=TenantShipment.ShipmentStatus.POD_SUBMITTED,
            pod_type=TenantShipment.PodType.DIGITAL,
            booking=SimpleNamespace(pod_type=TenantShipment.PodType.DIGITAL),
        )
        self.assertEqual(
            mobile_effective_shipment_status(
                shipment,
                TenantShipment.ShipmentStatus.POD_SUBMITTED,
            ),
            TenantShipment.ShipmentStatus.POD_SUBMITTED,
        )
