"""Tests for Hard POD confirmation page projection."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from mobile_api.hard_pod.services.delivery_note_pages import (
    build_hard_pod_confirmation_context,
    build_hard_pod_confirmation_pages,
)


class DeliveryNotePagesTests(SimpleTestCase):
    @patch(
        'mobile_api.hard_pod.services.delivery_note_pages._load_delivery_note_documents',
        return_value=[
            {
                'document_id': 'doc-1',
                'record_no': 'REC-0022',
                'document_type': 'Delivery Note',
                'document_ref_no': 'DN-1020',
                'document_date': '',
                'is_delivery_note': True,
                'page_count': 1,
                'status': 'Verified',
                'physical_location': 'In Company',
                'pages': [
                    {
                        'page_id': 'page-1',
                        'line_no': 1,
                        'label': 'IMG-(ABC-002)',
                        'physical_page_no': 1,
                        'confirmation_text': (
                            'I confirm the physical receipt of this original document of 1'
                        ),
                        'attachment_label': '',
                        'signer_location': '',
                        'completion_status': '',
                    }
                ],
            }
        ],
    )
    @patch('mobile_api.hard_pod.services.delivery_note_pages.schema_context')
    def test_builds_rows_from_document_pages(self, mock_schema, _mock_load):
        mock_schema.return_value.__enter__ = MagicMock(return_value=None)
        mock_schema.return_value.__exit__ = MagicMock(return_value=False)

        shipment = MagicMock()
        shipment.pk = uuid.uuid4()

        context = build_hard_pod_confirmation_context(
            shipment,
            tenant_schema='tenant_test',
        )
        rows = context['pages']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['label'], 'IMG-(ABC-002)')
        self.assertIn('physical receipt', rows[0]['confirmation_text'])
        self.assertEqual(len(context['documents']), 1)
        self.assertEqual(context['documents'][0]['document_ref_no'], 'DN-1020')

        flat_rows = build_hard_pod_confirmation_pages(shipment)
        self.assertEqual(len(flat_rows), 1)
