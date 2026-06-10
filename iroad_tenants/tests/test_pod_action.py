"""POD action side-effect classification tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from iroad_tenants.operation_runtime.pod_action import (
    apply_a7_shipment_pod_type_classification,
    apply_a7h_hard_pod_physical_posting,
    apply_pod_posting_from_action_log,
)
from tenant_workspace.models import TenantShipment, TenantShipmentDocumentPage


class ApplyA7PodTypeClassificationTests(TestCase):
    def test_hard_shipment_unchanged_after_a7(self):
        shipment = MagicMock()
        shipment.pk = 'shipment-1'
        shipment.booking_id = None
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.refresh_from_db = MagicMock()
        apply_a7_shipment_pod_type_classification(shipment)
        self.assertEqual(shipment.pod_type, TenantShipment.PodType.HARD)
        shipment.save.assert_not_called()

    def test_booking_hard_restores_shipment_hard_after_a7(self):
        shipment = MagicMock()
        shipment.pk = 'shipment-1'
        shipment.booking_id = 'booking-1'
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        shipment.booking = SimpleNamespace(pod_type=TenantShipment.PodType.HARD)
        shipment.refresh_from_db = MagicMock(
            side_effect=lambda fields=None: setattr(
                shipment,
                'pod_type',
                TenantShipment.PodType.DIGITAL,
            )
        )
        apply_a7_shipment_pod_type_classification(shipment)
        self.assertEqual(shipment.pod_type, TenantShipment.PodType.HARD)
        shipment.save.assert_called_once_with(update_fields=['pod_type', 'updated_at'])

    def test_non_hard_shipment_set_to_digital_on_a7(self):
        shipment = MagicMock()
        shipment.pk = 'shipment-1'
        shipment.booking_id = None
        shipment.booking = None
        shipment.pod_type = TenantShipment.PodType.SOFT
        shipment.refresh_from_db = MagicMock()
        apply_a7_shipment_pod_type_classification(shipment)
        self.assertEqual(shipment.pod_type, TenantShipment.PodType.DIGITAL)
        shipment.save.assert_called_once_with(update_fields=['pod_type', 'updated_at'])

    def test_empty_pod_type_defaults_to_digital_on_a7(self):
        shipment = MagicMock()
        shipment.pk = 'shipment-1'
        shipment.booking_id = None
        shipment.booking = None
        shipment.pod_type = ''
        shipment.refresh_from_db = MagicMock()
        apply_a7_shipment_pod_type_classification(shipment)
        self.assertEqual(shipment.pod_type, TenantShipment.PodType.DIGITAL)
        shipment.save.assert_called_once_with(update_fields=['pod_type', 'updated_at'])


class ApplyA7HardPodPostingTests(TestCase):
    def test_hard_pod_a7_uses_digital_posting_not_standard_in_company(self):
        shipment = MagicMock()
        shipment.pod_type = TenantShipment.PodType.HARD
        shipment.booking_id = None
        shipment.booking = None
        action_log = SimpleNamespace(
            operation_action=SimpleNamespace(action_code='A7', english_label='Upload POD'),
            log_no='LOG-0099',
        )
        pod_document = MagicMock()
        pod_document.source_document = MagicMock()

        with patch(
            'iroad_tenants.operation_runtime.pod_action._apply_a7_hard_pod_digital_posting',
        ) as mock_hard_posting:
            with patch(
                'iroad_tenants.views._tenant_shipment_pod_apply_posting_effects',
            ) as mock_standard_posting:
                with patch(
                    'iroad_tenants.operation_runtime.pod_action.apply_a7_shipment_pod_type_classification',
                ):
                    apply_pod_posting_from_action_log(
                        action_log=action_log,
                        pod_document=pod_document,
                        shipment=shipment,
                    )
                    mock_hard_posting.assert_called_once()
                    mock_standard_posting.assert_not_called()

    def test_digital_shipment_a7_uses_standard_posting(self):
        shipment = MagicMock()
        shipment.pod_type = TenantShipment.PodType.DIGITAL
        action_log = SimpleNamespace(
            operation_action=SimpleNamespace(action_code='A7', english_label='Upload POD'),
            log_no='LOG-0100',
        )
        pod_document = MagicMock()
        pod_document.source_document = MagicMock()

        with patch(
            'iroad_tenants.operation_runtime.pod_action._apply_a7_hard_pod_digital_posting',
        ) as mock_hard_posting:
            with patch(
                'iroad_tenants.views._tenant_shipment_pod_apply_posting_effects',
            ) as mock_standard_posting:
                with patch(
                    'iroad_tenants.operation_runtime.pod_action.apply_a7_shipment_pod_type_classification',
                ):
                    apply_pod_posting_from_action_log(
                        action_log=action_log,
                        pod_document=pod_document,
                        shipment=shipment,
                    )
                    mock_hard_posting.assert_not_called()
                    mock_standard_posting.assert_called_once()


class ApplyA7hHardPodPhysicalPostingTests(TestCase):
    @patch('iroad_tenants.views._tenant_shipment_document_refresh_shipment_pod')
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentPodPage')
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument')
    def test_marks_confirmed_pages_collected(
        self,
        mock_document_model,
        mock_pod_page_model,
        mock_refresh,
    ):
        shipment = MagicMock()
        shipment.booking_id = None
        document = MagicMock()
        document.pk = 'doc-1'
        page = MagicMock()
        page.pk = 'page-1'
        page.line_no = 1
        document.document_pages.order_by.return_value = [page]
        document.sync_pod_pages_from_document_pages = MagicMock()
        mock_document_model.objects.filter.return_value.prefetch_related.return_value = [
            document
        ]
        mock_document_model.objects.filter.return_value.order_by.return_value.first.return_value = (
            None
        )

        apply_a7h_hard_pod_physical_posting(
            action_log=MagicMock(),
            shipment=shipment,
            confirmed_pages=[
                {'page_id': 'page-1', 'document_id': 'doc-1', 'line_no': 1},
            ],
        )

        self.assertEqual(
            page.completion_status,
            TenantShipmentDocumentPage.CompletionStatus.COMPLETED,
        )
        mock_refresh.assert_called_once_with(shipment)
