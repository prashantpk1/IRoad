"""Shipment document gate respects per-leg documents on round trips."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.pod_action import (
    POD_REQUIRES_SHIPMENT_DOCUMENT_MSG,
    build_shipment_document_gate,
    portal_shipment_document_exists,
)


class ShipmentDocumentGateRoundTripTests(SimpleTestCase):
    def _round_booking(self):
        return SimpleNamespace(pk='bk-1', trip_type='Round')

    @patch(
        'iroad_tenants.operation_runtime.pod_action._booking_shipment_leg_count',
        return_value=2,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_pod_source_shipment_document',
        return_value=None,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_booking_for_shipment',
    )
    def test_round_trip_backload_not_ready_when_only_outbound_document_exists(
        self,
        mock_booking,
        _resolve_doc,
        _leg_count,
    ):
        mock_booking.return_value = self._round_booking()
        outbound_doc = SimpleNamespace(pk='doc-out')
        backload_shipment = SimpleNamespace(
            pk='ship-back',
            shipment_no='SH-0137',
            booking_id='bk-1',
            booking=self._round_booking(),
            booking_item_type='Backload',
            pod_doc_count=1,
            pod_type='Hard Copy',
        )

        with patch(
            'iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument',
        ) as mock_model:
            mock_model.objects.filter.return_value.exclude.return_value.exists.return_value = (
                True
            )
            self.assertFalse(portal_shipment_document_exists(backload_shipment))

    @patch(
        'iroad_tenants.operation_runtime.pod_action._booking_shipment_leg_count',
        return_value=2,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_pod_source_shipment_document',
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_booking_for_shipment',
    )
    @patch(
        'iroad_tenants.operation_field_catalog.operation_shipment_uses_hard_copy_pod',
        return_value=True,
    )
    def test_gate_message_names_backload_shipment_on_round_trip(
        self,
        _hard_pod,
        mock_booking,
        mock_resolve_doc,
        _leg_count,
    ):
        mock_booking.return_value = self._round_booking()
        mock_resolve_doc.return_value = None
        shipment = SimpleNamespace(
            pk='ship-back',
            shipment_no='SH-0137',
            booking_id='bk-1',
            booking=self._round_booking(),
            pod_doc_count=1,
        )

        gate = build_shipment_document_gate(shipment)

        self.assertTrue(gate['required'])
        self.assertFalse(gate['ready'])
        self.assertIn('SH-0137', gate['message'])
        self.assertNotEqual(gate['message'], POD_REQUIRES_SHIPMENT_DOCUMENT_MSG)

    @patch(
        'iroad_tenants.operation_runtime.pod_action._booking_shipment_leg_count',
        return_value=2,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_pod_source_shipment_document',
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_booking_for_shipment',
    )
    @patch(
        'iroad_tenants.operation_field_catalog.operation_shipment_uses_hard_copy_pod',
        return_value=True,
    )
    def test_gate_ready_when_current_leg_has_document(
        self,
        _hard_pod,
        mock_booking,
        mock_resolve_doc,
        _leg_count,
    ):
        mock_booking.return_value = self._round_booking()
        mock_resolve_doc.return_value = SimpleNamespace(pk='doc-back')
        shipment = SimpleNamespace(
            pk='ship-back',
            shipment_no='SH-0137',
            booking_id='bk-1',
            booking=self._round_booking(),
            pod_doc_count=1,
        )

        gate = build_shipment_document_gate(shipment)

        self.assertTrue(gate['required'])
        self.assertTrue(gate['ready'])
        self.assertEqual(gate['message'], '')

    @patch(
        'iroad_tenants.operation_runtime.pod_action._booking_shipment_leg_count',
        return_value=1,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_pod_source_shipment_document',
        return_value=None,
    )
    @patch(
        'iroad_tenants.operation_runtime.pod_action._resolve_booking_for_shipment',
    )
    def test_first_round_leg_may_use_booking_scoped_preshipment_document(
        self,
        mock_booking,
        _resolve_doc,
        _leg_count,
    ):
        mock_booking.return_value = self._round_booking()
        shipment = SimpleNamespace(
            pk='ship-out',
            booking_id='bk-1',
            booking=self._round_booking(),
        )

        with patch(
            'iroad_tenants.operation_runtime.pod_action._portal_preshipment_document_for_booking',
            return_value=True,
        ) as mock_preship:
            self.assertTrue(portal_shipment_document_exists(shipment))
        mock_preship.assert_called_once()
