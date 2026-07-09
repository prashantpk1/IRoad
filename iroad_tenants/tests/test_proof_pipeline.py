"""Tests for 3-layer proof pipeline rules."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from iroad_tenants.operation_runtime.proof_pipeline import (
    apply_shipment_document_line_rules,
    document_handover_allowed,
    expected_pod_page_line_count,
    requires_single_document_page,
    resolve_shipment_pod_evidence_display,
    shipment_auto_pod_document_flow,
    shipment_pod_list_stats,
    validate_handover_page_line_count,
    validate_manual_pod_page_lines,
    validate_manual_shipment_document_create,
    validate_pod_page_line_count,
)
from tenant_workspace.models import TenantShipment


class ProofPipelineTests(TestCase):
    def _shipment(self, *, pod_type='Digital', booking_pod_type=''):
        booking = SimpleNamespace(pod_type=booking_pod_type) if booking_pod_type else None
        return SimpleNamespace(pod_type=pod_type, booking=booking)

    def _document(self, *, is_delivery_note=False, page_count=1, page_rows=None):
        pages = page_rows or []
        doc = SimpleNamespace(
            is_delivery_note=is_delivery_note,
            page_count=page_count,
        )
        doc.document_pages = SimpleNamespace(
            order_by=lambda _field: pages,
        )
        return doc

    def test_digital_non_dn_requires_single_page(self):
        shipment = self._shipment(pod_type=TenantShipment.PodType.DIGITAL)
        self.assertTrue(
            requires_single_document_page(shipment, is_delivery_note=False),
        )
        rows, errors = apply_shipment_document_line_rules(
            shipment=shipment,
            is_delivery_note=False,
            line_rows=[{}, {}, {}],
        )
        self.assertEqual(len(rows), 1)
        self.assertIn('page_count', errors)

    def test_dn_allows_multiple_subform_rows(self):
        shipment = self._shipment(pod_type=TenantShipment.PodType.DIGITAL)
        rows, errors = apply_shipment_document_line_rules(
            shipment=shipment,
            is_delivery_note=True,
            line_rows=[{}, {}, {}],
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(errors, {})

    def test_expected_pod_pages_match_document_subform(self):
        shipment = self._shipment(pod_type=TenantShipment.PodType.HARD)
        page = SimpleNamespace(pk='p1', physical_page_no=1, line_no=1)
        doc = self._document(is_delivery_note=True, page_rows=[page, page, page])
        self.assertEqual(expected_pod_page_line_count(doc, shipment), 3)

    def test_validate_pod_page_count_mismatch(self):
        shipment = self._shipment(pod_type=TenantShipment.PodType.DIGITAL)
        doc = self._document(is_delivery_note=True, page_count=2)
        message = validate_pod_page_line_count(
            source_document=doc,
            shipment=shipment,
            line_count=1,
        )
        self.assertIsNotNone(message)
        self.assertIn('exactly 2', message)

    def test_manual_pod_requires_map_and_attachment_when_posted(self):
        errors = validate_manual_pod_page_lines(
            [
                (
                    1,
                    {
                        'source': 'Manual',
                        'action_log': None,
                        'map_url': '',
                        'attachment_storage_path': '',
                    },
                ),
            ],
            is_posted=True,
        )
        self.assertIn('pod_pages', errors)

    def test_handover_blocked_for_digital_pod(self):
        shipment = self._shipment(pod_type=TenantShipment.PodType.DIGITAL)
        self.assertFalse(document_handover_allowed(shipment))

    def test_handover_page_count_matches_subform(self):
        shipment = self._shipment(pod_type=TenantShipment.PodType.HARD)
        page = SimpleNamespace(pk='p1', physical_page_no=1, line_no=1)
        doc = self._document(is_delivery_note=True, page_rows=[page, page])
        message = validate_handover_page_line_count(
            source_document=doc,
            shipment=shipment,
            line_count=1,
        )
        self.assertIsNotNone(message)
        self.assertIn('exactly 2', message)

    def test_shipment_pod_evidence_display_never_hard_copy(self):
        page_digital = SimpleNamespace(
            digital_evidence_status='Collected',
            soft_copy_status='',
        )
        doc = SimpleNamespace(pod_pages=[page_digital])
        display = resolve_shipment_pod_evidence_display(doc)
        self.assertEqual(display['evidence_type'], 'Digital Evidence')
        self.assertNotIn('Hard', display['evidence_type'])

    def test_auto_pod_blocks_duplicate_manual_delivery_note(self):
        shipment = SimpleNamespace(pod_doc_count=2)
        existing = SimpleNamespace(record_no='REC-0100', notes='')
        with patch(
            'iroad_tenants.operation_runtime.proof_pipeline.shipment_existing_delivery_note',
            return_value=existing,
        ):
            message = validate_manual_shipment_document_create(
                shipment=shipment,
                is_delivery_note=True,
                document_type='Delivery Note',
            )
        self.assertIsNotNone(message)
        self.assertIn('REC-0100', message)

    def test_auto_pod_allows_editing_existing_delivery_note(self):
        shipment = SimpleNamespace(pod_doc_count=2)
        with patch(
            'iroad_tenants.operation_runtime.proof_pipeline.shipment_existing_delivery_note',
            return_value=None,
        ):
            message = validate_manual_shipment_document_create(
                shipment=shipment,
                is_delivery_note=True,
                document_type='delivery_note',
                editing_document_id='doc-1',
            )
        self.assertIsNone(message)

    def test_manual_create_allows_non_delivery_note(self):
        shipment = SimpleNamespace(pod_doc_count=2)
        existing = SimpleNamespace(record_no='REC-0100', notes='')
        with patch(
            'iroad_tenants.operation_runtime.proof_pipeline.shipment_existing_delivery_note',
            return_value=existing,
        ):
            message = validate_manual_shipment_document_create(
                shipment=shipment,
                is_delivery_note=False,
                document_type='Commercial Invoice',
            )
        self.assertIsNone(message)

    def test_shipment_auto_pod_document_flow_requires_pod_doc_count(self):
        self.assertFalse(shipment_auto_pod_document_flow(SimpleNamespace(pod_doc_count=0)))
        self.assertTrue(shipment_auto_pod_document_flow(SimpleNamespace(pod_doc_count=1)))
