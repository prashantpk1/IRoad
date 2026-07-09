"""POD page count mirrors to shipment and booking pod_doc_count."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from iroad_tenants.views import (
    _tenant_shipment_apply_pod_doc_count,
    _tenant_shipment_count_pod_pages,
    _tenant_shipment_document_resolve_page_count,
    _tenant_shipment_document_sync_page_count_after_save,
    _tenant_shipment_op_doc_page_count,
)


class ShipmentPodDocCountSyncTests(TestCase):
    @patch('iroad_tenants.views.TenantShipmentPodPage')
    @patch('iroad_tenants.views.TenantShipmentDocument')
    def test_count_pod_pages_from_pod_documents(self, mock_document_model, mock_pod_page_model):
        mock_document_model.objects.filter.return_value.values_list.return_value = ['pod-1']
        mock_pod_page_model.objects.filter.return_value.count.return_value = 3
        shipment = SimpleNamespace(pk='sh-1')
        self.assertEqual(_tenant_shipment_count_pod_pages(shipment), 3)

    @patch('iroad_tenants.views._tenant_booking_sync_pod_doc_count_from_shipment')
    def test_apply_pod_doc_count_updates_shipment(self, mock_sync):
        shipment = SimpleNamespace(pod_doc_count=0, save=MagicMock())
        _tenant_shipment_apply_pod_doc_count(shipment, 2)
        self.assertEqual(shipment.pod_doc_count, 2)
        shipment.save.assert_called_once()
        mock_sync.assert_called_once_with(shipment)

    @patch('iroad_tenants.views.TenantShipmentDocument')
    def test_op_doc_page_count_includes_non_delivery_note_documents(self, mock_document_model):
        base_qs = MagicMock()
        dn_qs = MagicMock()
        mock_document_model.objects.filter.return_value.exclude.return_value = base_qs
        base_qs.filter.return_value = dn_qs
        dn_qs.exists.return_value = False
        base_qs.aggregate.return_value = {'total': 2}

        shipment = SimpleNamespace(pk='sh-1')
        self.assertEqual(_tenant_shipment_op_doc_page_count(shipment), 2)

    @patch('iroad_tenants.views._tenant_shipment_document_refresh_shipment_pod')
    @patch('iroad_tenants.views._tenant_shipment_document_resolve_page_count', return_value=3)
    def test_sync_page_count_after_save_updates_header_and_shipment(
        self,
        _resolve,
        mock_refresh,
    ):
        document = SimpleNamespace(
            page_count=1,
            shipment_id='sh-1',
            shipment=SimpleNamespace(pk='sh-1'),
            save=MagicMock(),
        )
        _tenant_shipment_document_sync_page_count_after_save(document)
        self.assertEqual(document.page_count, 3)
        document.save.assert_called_once()
        mock_refresh.assert_called_once_with(document.shipment)

    @patch('iroad_tenants.views.TenantShipmentPodPage')
    @patch('iroad_tenants.views.TenantShipmentDocumentPage')
    def test_resolve_page_count_prefers_saved_lines(self, mock_doc_page_model, mock_pod_page_model):
        mock_doc_page_model.objects.filter.return_value.count.return_value = 2
        mock_pod_page_model.objects.filter.return_value.count.return_value = 0
        document = SimpleNamespace(page_count=1)
        self.assertEqual(_tenant_shipment_document_resolve_page_count(document), 2)
