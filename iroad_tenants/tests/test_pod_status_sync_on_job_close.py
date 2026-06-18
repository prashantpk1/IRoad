"""POD status column sync when mobile execution completes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.latest_state import after_shipment_status_side_effects
from iroad_tenants.operation_runtime.side_effects import (
    derive_pod_status_from_shipment_rows,
    sync_booking_pod_status_from_shipments,
)
from tenant_workspace.models import TenantShipment


class DerivePodStatusFromShipmentRowsTests(SimpleTestCase):
    def test_all_completed_returns_completed(self):
        statuses = [
            TenantShipment.PodStatus.COMPLETED,
            TenantShipment.PodStatus.COMPLETED,
        ]
        self.assertEqual(
            derive_pod_status_from_shipment_rows(statuses),
            TenantShipment.PodStatus.COMPLETED,
        )

    def test_any_not_completed_wins(self):
        statuses = [
            TenantShipment.PodStatus.COMPLETED,
            TenantShipment.PodStatus.NOT_COMPLETED,
        ]
        self.assertEqual(
            derive_pod_status_from_shipment_rows(statuses),
            TenantShipment.PodStatus.NOT_COMPLETED,
        )


class AfterShipmentStatusSideEffectsPodSyncTests(SimpleTestCase):
    @patch('iroad_tenants.operation_runtime.side_effects.sync_booking_pod_status_from_shipments')
    @patch('iroad_tenants.operation_runtime.side_effects._sync_pod_status_from_mobile_logs')
    @patch('iroad_tenants.views._tenant_shipment_document_refresh_shipment_pod')
    @patch(
        'iroad_tenants.operation_runtime.latest_state.auto_complete_loaded_movement_for_shipment',
    )
    def test_closed_shipment_reapplies_mobile_pod_status_after_document_refresh(
        self,
        _auto_complete,
        mock_refresh,
        mock_sync_shipment_pod,
        mock_sync_booking_pod,
    ):
        shipment = SimpleNamespace(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
            booking_id='booking-1',
            booking=SimpleNamespace(booking_id='booking-1', pod_status='Not Completed'),
        )
        after_shipment_status_side_effects(shipment)
        mock_refresh.assert_called_once_with(shipment)
        mock_sync_shipment_pod.assert_called_once_with(shipment)
        mock_sync_booking_pod.assert_called_once_with(shipment.booking)


class SyncBookingPodStatusFromShipmentsTests(SimpleTestCase):
    @patch('tenant_workspace.models.TenantBooking')
    @patch('iroad_tenants.operation_runtime.side_effects.TenantShipment.objects')
    def test_updates_booking_when_all_shipments_completed(
        self,
        mock_shipment_objects,
        mock_booking_model,
    ):
        booking = SimpleNamespace(booking_id='booking-1', pk='booking-1', pod_status='Not Completed')
        mock_shipment_objects.filter.return_value.exclude.return_value.values_list.return_value = [
            TenantShipment.PodStatus.COMPLETED,
        ]
        sync_booking_pod_status_from_shipments(booking)
        mock_booking_model.objects.filter.return_value.update.assert_called_once()
        self.assertEqual(booking.pod_status, TenantShipment.PodStatus.COMPLETED)
