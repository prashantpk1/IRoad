"""Delivery-note scaffold respects booking line POD doc count."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.pod_action import (
    _birth_delivery_note_scaffold,
    _shipment_target_pod_doc_count,
)
from tenant_workspace.models import TenantShipment, TenantShipmentDocument


class ShipmentPodDocCountTests(SimpleTestCase):
    def test_target_from_shipment_column(self):
        shipment = SimpleNamespace(pod_doc_count=5, booking_id=None, booking=None)
        self.assertEqual(_shipment_target_pod_doc_count(shipment), 5)

    def test_target_from_booking_outbound_line(self):
        booking = SimpleNamespace(
            booking_line_pod_doc_count=5,
            booking_line_backload_pod_doc_count=2,
        )
        shipment = SimpleNamespace(
            pod_doc_count=0,
            booking_item_type='Outbound',
            booking=booking,
            booking_id='bk-1',
        )
        self.assertEqual(_shipment_target_pod_doc_count(shipment), 5)

    def test_target_from_booking_backload_line(self):
        booking = SimpleNamespace(
            booking_line_pod_doc_count=1,
            booking_line_backload_pod_doc_count=4,
        )
        shipment = SimpleNamespace(
            pod_doc_count=0,
            booking_item_type='Backload',
            booking=booking,
            booking_id='bk-1',
        )
        self.assertEqual(_shipment_target_pod_doc_count(shipment), 4)

    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocumentPage')
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument')
    @patch('iroad_tenants.operation_runtime.pod_action._sync_shipment_pod_doc_count_from_booking')
    def test_birth_scaffold_creates_page_count_from_booking(
        self,
        mock_sync,
        mock_document_model,
        mock_page_model,
    ):
        mock_sync.return_value = 5
        mock_document_model.objects.filter.return_value.order_by.return_value.first.return_value = (
            None
        )
        shipment = SimpleNamespace(
            pk='sh-1',
            shipment_no='SH-100',
            booking_id='bk-1',
            booking=SimpleNamespace(
                booking_line_pod_doc_count=5,
                booking_line_backload_pod_doc_count=2,
            ),
            booking_item_type='Outbound',
            pod_doc_count=5,
            save=MagicMock(),
        )
        created_doc = MagicMock()
        created_doc.document_ref_no = 'SH-100'
        created_doc.record_no = 'REC-1'
        created_doc.page_count = 5
        created_doc.save = MagicMock()

        with patch(
            'iroad_tenants.views._next_auto_number_for_form',
            return_value=('REC-1', 1),
        ), patch(
            'iroad_tenants.views._tenant_shipment_document_apply_foreign_keys',
        ), patch(
            'iroad_tenants.operation_runtime.pod_action._ensure_delivery_note_pages',
        ) as mock_ensure:
            mock_document_model.return_value = created_doc
            mock_document_model.Status = TenantShipmentDocument.Status
            result = _birth_delivery_note_scaffold(shipment, created_by_label='test')

        self.assertIs(result, created_doc)
        self.assertEqual(created_doc.page_count, 5)
        mock_ensure.assert_called_once()
