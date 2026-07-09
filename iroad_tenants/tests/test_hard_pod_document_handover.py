"""Document Handover auto-birth from mobile Hard POD promotion."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from iroad_tenants.operation_runtime.hard_pod_document_handover import (
    MOBILE_HARD_POD_HANDOVER_NOTE_PREFIX,
    ensure_document_handover_from_hard_pod_promotion,
)


class HardPodDocumentHandoverBirthTests(SimpleTestCase):
    @patch(
        'iroad_tenants.operation_runtime.hard_pod_document_handover._finalize_mobile_handover_posted',
    )
    @patch(
        'iroad_tenants.operation_runtime.hard_pod_document_handover.TenantDocumentHandoverLine',
    )
    @patch(
        'iroad_tenants.operation_runtime.hard_pod_document_handover.TenantDocumentHandover',
    )
    @patch(
        'iroad_tenants.operation_runtime.hard_pod_document_handover._existing_handover_for_action_log',
        return_value=None,
    )
    @patch(
        'iroad_tenants.operation_runtime.proof_pipeline.document_handover_allowed',
        return_value=True,
    )
    def test_births_and_posts_handover_on_promotion(
        self,
        _allowed,
        _existing,
        mock_handover_model,
        mock_line_model,
        mock_finalize,
    ):
        shipment = SimpleNamespace(pk='ship-1', booking_id=None, booking=None)
        action_log = SimpleNamespace(log_id='log-99', log_date=None)
        dn_page = SimpleNamespace(pk='page-1', line_no=1, doc_ref_no='DN-P1')
        source_document = SimpleNamespace(
            pk='doc-1',
            document_pages=MagicMock(),
        )
        source_document.document_pages.order_by.return_value = [dn_page]
        pod_line = SimpleNamespace(line_no=1, doc_page='DN-P1')
        pod_document = SimpleNamespace(pk='pod-1')

        with patch(
            'iroad_tenants.operation_runtime.hard_pod_document_handover._resolve_delivery_note',
            return_value=source_document,
        ), patch(
            'iroad_tenants.operation_runtime.hard_pod_document_handover._resolve_pod_child',
            return_value=pod_document,
        ), patch(
            'iroad_tenants.operation_runtime.hard_pod_document_handover._resolve_pod_line_for_dn_page',
            return_value=pod_line,
        ), patch(
            'iroad_tenants.views._next_auto_number_for_form',
            return_value=('DH-0099', 99),
        ), patch.object(
            mock_handover_model.objects,
            'filter',
        ) as mock_filter, patch.object(
            mock_handover_model,
            'Status',
            SimpleNamespace(DRAFT='Draft', POSTED='Posted'),
        ):
            mock_filter.return_value.exists.return_value = False
            created = MagicMock(handover_no='DH-0099')
            mock_handover_model.objects.create.return_value = created
            posted = MagicMock(handover_no='DH-0099', status='Posted')
            mock_finalize.return_value = posted

            submission = SimpleNamespace(receiver_name='Site Receiver')
            with patch(
                'iroad_tenants.operation_runtime.hard_pod_document_handover.transaction.atomic',
            ):
                result = ensure_document_handover_from_hard_pod_promotion(
                    shipment=shipment,
                    action_log=action_log,
                    confirmed_pages=[
                        {'page_id': 'page-1', 'document_id': 'doc-1', 'line_no': 1},
                    ],
                    custody_submission=submission,
                    created_by_label='DRV-1',
                )

        self.assertIs(result, posted)
        create_kwargs = mock_handover_model.objects.create.call_args.kwargs
        self.assertEqual(create_kwargs['status'], 'Draft')
        self.assertEqual(create_kwargs['physical_location'], 'With Driver')
        self.assertTrue(
            create_kwargs['notes'].startswith(MOBILE_HARD_POD_HANDOVER_NOTE_PREFIX),
        )
        mock_line_model.objects.create.assert_called_once()
        mock_finalize.assert_called_once_with(
            handover=created,
            source_document=source_document,
            shipment=shipment,
        )

    @patch(
        'iroad_tenants.operation_runtime.hard_pod_document_handover._finalize_mobile_handover_posted',
    )
    @patch(
        'iroad_tenants.operation_runtime.hard_pod_document_handover._existing_handover_for_action_log',
    )
    @patch(
        'iroad_tenants.operation_runtime.proof_pipeline.document_handover_allowed',
        return_value=True,
    )
    def test_existing_draft_handover_is_upgraded_to_posted(
        self,
        _allowed,
        mock_existing_lookup,
        mock_finalize,
    ):
        shipment = SimpleNamespace(pk='ship-1', booking_id=None, booking=None)
        action_log = SimpleNamespace(log_id='log-99', log_date=None)
        source_document = SimpleNamespace(pk='doc-1')
        existing = MagicMock(status='Draft')
        mock_existing_lookup.return_value = existing
        posted = MagicMock(status='Posted')
        mock_finalize.return_value = posted

        with patch(
            'iroad_tenants.operation_runtime.hard_pod_document_handover._resolve_delivery_note',
            return_value=source_document,
        ):
            result = ensure_document_handover_from_hard_pod_promotion(
                shipment=shipment,
                action_log=action_log,
            )

        self.assertIs(result, posted)
        mock_finalize.assert_called_once_with(
            handover=existing,
            source_document=source_document,
            shipment=shipment,
        )
