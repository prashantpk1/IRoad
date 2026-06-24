"""Round-trip job close cascades to sibling delivered legs."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.booking_status import (
    BOOKING_ITEM_COMPLETED,
    BOOKING_ITEM_IN_PROGRESS,
    derive_booking_line_status,
)
from iroad_tenants.operation_runtime.side_effects import (
    _peer_ready_for_round_trip_cascade_close,
    close_round_trip_peer_shipments_on_job_close,
)
from tenant_workspace.models import TenantShipment


def _delivered_cod_shipment(**kwargs):
    shipment = SimpleNamespace(
        pk=kwargs.pop('pk', 'sh-peer'),
        shipment_id=kwargs.pop('shipment_id', 'sh-peer'),
        shipment_no=kwargs.pop('shipment_no', 'SH-0100'),
        booking_item_type=kwargs.pop('booking_item_type', 'Outbound'),
        shipment_status=TenantShipment.ShipmentStatus.DELIVERED,
        order_type='COD',
        collection_status=TenantShipment.CollectionStatus.COLLECTED,
        pod_status=TenantShipment.PodStatus.COMPLETED,
        booking_id='bk-1',
        booking=None,
        save=MagicMock(),
    )
    for key, value in kwargs.items():
        setattr(shipment, key, value)
    return shipment


class PeerReadyForRoundTripCascadeCloseTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_runtime.side_effects._mobile_pod_compliance_satisfied',
        return_value=True,
    )
    def test_delivered_cod_peer_is_ready(self, _pod):
        self.assertTrue(_peer_ready_for_round_trip_cascade_close(_delivered_cod_shipment()))

    def test_closed_peer_is_not_ready(self):
        shipment = _delivered_cod_shipment(
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
        )
        self.assertFalse(_peer_ready_for_round_trip_cascade_close(shipment))


class CloseRoundTripPeerShipmentsTests(SimpleTestCase):
    @patch('iroad_tenants.operation_runtime.side_effects.apply_booking_status_impact')
    @patch('iroad_tenants.operation_runtime.side_effects.after_shipment_status_side_effects')
    @patch('iroad_tenants.operation_runtime.side_effects._ensure_auto_close_job_log')
    @patch(
        'iroad_tenants.operation_runtime.side_effects._peer_ready_for_round_trip_cascade_close',
        return_value=True,
    )
    @patch('iroad_tenants.operation_runtime.side_effects.TenantShipment.objects')
    @patch(
        'iroad_tenants.operation_runtime.side_effects.resolve_effective_shipment_status_for_action',
        return_value=TenantShipment.ShipmentStatus.CLOSED,
    )
    @patch(
        'mobile_api.dashboard.selectors.booking_selection_policy.normalized_trip_type',
        return_value='Round',
    )
    def test_backload_job_close_closes_outbound_peer(
        self,
        _trip_type,
        _resolve_impact,
        mock_objects,
        _peer_ready,
        mock_ensure_log,
        mock_after_effects,
        mock_booking_impact,
    ):
        booking = SimpleNamespace(pk='bk-1', booking_id='bk-1', trip_type='Round')
        outbound = _delivered_cod_shipment(
            pk='sh-out',
            shipment_no='SH-0100',
            booking_item_type='Outbound',
            booking=booking,
        )
        backload = _delivered_cod_shipment(
            pk='sh-back',
            shipment_no='SH-0101',
            booking_item_type='Backload',
            booking=booking,
        )
        mock_objects.filter.return_value.exclude.return_value.exclude.return_value = [
            outbound,
        ]
        action = SimpleNamespace(
            shipment_status_impact='Closed',
            booking_status_impact='Completed',
        )
        action_log = SimpleNamespace(booking=booking)

        closed = close_round_trip_peer_shipments_on_job_close(
            backload,
            action=action,
            action_log=action_log,
            created_by_label='driver',
        )

        self.assertEqual(closed, 1)
        self.assertEqual(outbound.shipment_status, TenantShipment.ShipmentStatus.CLOSED)
        outbound.save.assert_called_once()
        mock_ensure_log.assert_called_once()
        mock_after_effects.assert_called_once_with(outbound)
        mock_booking_impact.assert_called_once_with(booking, 'Completed')

    @patch(
        'mobile_api.dashboard.selectors.booking_selection_policy.normalized_trip_type',
        return_value='One Way',
    )
    @patch(
        'iroad_tenants.operation_runtime.side_effects.resolve_effective_shipment_status_for_action',
        return_value=TenantShipment.ShipmentStatus.CLOSED,
    )
    def test_one_way_booking_skips_cascade(self, _resolve, _trip_type):
        booking = SimpleNamespace(pk='bk-1', booking_id='bk-1', trip_type='One Way')
        shipment = _delivered_cod_shipment(booking=booking, booking_id='bk-1')
        action = SimpleNamespace(shipment_status_impact='Closed')
        self.assertEqual(
            close_round_trip_peer_shipments_on_job_close(shipment, action=action),
            0,
        )


class DeriveBookingLineStatusAfterCascadeTests(SimpleTestCase):
    def test_both_legs_closed_show_completed(self):
        booking = SimpleNamespace(
            booking_id='bk-1',
            booking_status='Confirmed',
            trip_type='Round',
        )
        outbound = SimpleNamespace(
            booking_item_type='Outbound',
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
        )
        backload = SimpleNamespace(
            booking_item_type='Backload',
            shipment_status=TenantShipment.ShipmentStatus.CLOSED,
        )

        with patch('tenant_workspace.models.TenantShipment.objects') as mock_objects:
            def _filter_side_effect(**kwargs):
                qs = MagicMock()
                line_type = kwargs.get('booking_item_type')
                if line_type == 'Outbound':
                    qs.exists.return_value = True
                    qs.exclude.return_value.exists.return_value = False
                    qs.filter.return_value.exists.return_value = True
                elif line_type == 'Backload':
                    qs.exists.return_value = True
                    qs.exclude.return_value.exists.return_value = False
                    qs.filter.return_value.exists.return_value = True
                return qs

            mock_objects.filter.side_effect = _filter_side_effect

            self.assertEqual(
                derive_booking_line_status(booking, 'Outbound'),
                BOOKING_ITEM_COMPLETED,
            )
            self.assertEqual(
                derive_booking_line_status(booking, 'Backload'),
                BOOKING_ITEM_COMPLETED,
            )

    def test_one_leg_delivered_stays_in_progress(self):
        booking = SimpleNamespace(
            booking_id='bk-1',
            booking_status='Confirmed',
            trip_type='Round',
        )

        with patch('tenant_workspace.models.TenantShipment.objects') as mock_objects:
            def _filter_side_effect(**kwargs):
                qs = MagicMock()
                line_type = kwargs.get('booking_item_type')
                if line_type == 'Outbound':
                    qs.exists.return_value = True
                    qs.exclude.return_value.exists.return_value = True
                elif line_type == 'Backload':
                    qs.exists.return_value = True
                    qs.exclude.return_value.exists.return_value = False
                    qs.filter.return_value.exists.return_value = False
                return qs

            mock_objects.filter.side_effect = _filter_side_effect

            self.assertEqual(
                derive_booking_line_status(booking, 'Outbound'),
                BOOKING_ITEM_IN_PROGRESS,
            )
