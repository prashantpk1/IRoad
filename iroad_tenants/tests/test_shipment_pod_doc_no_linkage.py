"""Shipment POD Doc No linkage — document auto, shipment manual."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from iroad_tenants.shipment_pod_form import apply_doc_no_linkage


class ShipmentPodDocNoLinkageTests(TestCase):
    @patch('iroad_tenants.shipment_pod_form.TenantShipmentDocument')
    def test_apply_doc_no_linkage_sets_document_fields_only(self, mock_document_model):
        shipment = SimpleNamespace(pk='sh-1', booking_id='bk-1', booking_item_ref='SV-1')
        document = SimpleNamespace(
            pk='dn-1',
            shipment_id='sh-1',
            shipment=shipment,
            booking=None,
            document_ref_no='PENDING',
            document_type='delivery_note',
            document_date=None,
            page_count=2,
        )
        mock_document_model.objects.filter.return_value.select_related.return_value.first.return_value = (
            document
        )
        form_data = {'doc_no': 'dn-1'}
        form_errors = {}
        result = apply_doc_no_linkage(form_data, form_errors)
        self.assertIs(result, document)
        self.assertEqual(form_data['source_document_id'], 'dn-1')
        self.assertEqual(form_data['document_ref_no'], '')
        self.assertEqual(form_data['page_count'], '2')
        self.assertNotIn('shipment_id', form_data)
        self.assertNotIn('pod_type', form_data)
