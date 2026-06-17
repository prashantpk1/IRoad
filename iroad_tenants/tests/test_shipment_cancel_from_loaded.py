"""Shipment cancel validation from Loaded."""
from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError

from tenant_workspace.models import TenantShipment


class ShipmentCancelFromLoadedTests(TestCase):
    def test_cancel_from_loaded_allowed_with_original_status(self):
        shipment = TenantShipment(
            shipment_status=TenantShipment.ShipmentStatus.CANCELLED,
        )
        shipment.pk = 'ship-1'
        shipment._original_shipment_status = TenantShipment.ShipmentStatus.LOADED
        shipment.booking_id = 'booking-1'
        shipment.booking_item_ref = 'SV-0001'
        shipment.order_type = 'COD'
        with patch.object(TenantShipment.objects, 'filter') as mock_filter:
            mock_filter.return_value.values_list.return_value.first.return_value = (
                TenantShipment.ShipmentStatus.DELIVERED
            )
            shipment.clean()

    def test_cancel_from_closed_blocked_even_if_db_was_overwritten(self):
        shipment = TenantShipment(
            shipment_status=TenantShipment.ShipmentStatus.CANCELLED,
        )
        shipment.pk = 'ship-1'
        shipment._original_shipment_status = TenantShipment.ShipmentStatus.CLOSED
        shipment.booking_id = 'booking-1'
        shipment.booking_item_ref = 'SV-0001'
        shipment.order_type = 'COD'
        with self.assertRaises(ValidationError):
            shipment.clean()

    def test_cancel_syncs_cod_collection_status(self):
        shipment = TenantShipment(
            shipment_status=TenantShipment.ShipmentStatus.CANCELLED,
            order_type='COD',
            cod_amount=100,
            collection_status=TenantShipment.CollectionStatus.PENDING,
        )
        shipment.sync_collection_status_for_lifecycle()
        self.assertEqual(
            shipment.collection_status,
            TenantShipment.CollectionStatus.CANCELLED,
        )

    def test_cod_payment_status_helper_reflects_cancelled_shipment(self):
        from iroad_tenants.views import _tenant_shipment_cod_payment_status

        shipment = TenantShipment(
            shipment_status=TenantShipment.ShipmentStatus.CANCELLED,
            order_type='COD',
            cod_amount=50,
            collection_status=TenantShipment.CollectionStatus.PENDING,
        )
        self.assertEqual(
            _tenant_shipment_cod_payment_status(shipment),
            TenantShipment.CollectionStatus.CANCELLED,
        )
