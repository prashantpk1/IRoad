"""POD action side-effect classification tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from iroad_tenants.operation_runtime.pod_action import (
    _allocate_unique_pod_record_no,
    _find_existing_pod_for_source,
    _sync_a7_action_log_media_to_pod_pages,
    apply_a7_shipment_pod_type_classification,
    apply_a7h_hard_pod_physical_posting,
    apply_pod_posting_from_action_log,
    birth_pod_from_action_log,
    sync_a7_pod_evidence_attachments,
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


class SyncA7ActionLogMediaToPodPagesTests(TestCase):
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentPodPage')
    def test_writes_media_directly_to_pod_pages_without_delivery_note(self, mock_pod_page_model):
        photo = SimpleNamespace(
            file=SimpleNamespace(name='uploads/photo1.jpg'),
            media_type='photo',
            description='',
        )
        video = SimpleNamespace(
            file=SimpleNamespace(name='uploads/clip.mp4'),
            media_type='video',
            description='',
        )
        action_log = MagicMock()
        action_log.pk = 'log-1'
        action_log.media_rows.all.return_value.order_by.return_value = [photo, video]

        pod_line_1 = MagicMock()
        pod_line_2 = MagicMock()
        pod_line_3 = MagicMock()
        mock_pod_page_model.objects.filter.return_value.order_by.return_value = [
            pod_line_1,
        ]
        mock_pod_page_model.objects.create.side_effect = [pod_line_2, pod_line_3]

        pod_document = MagicMock()
        _sync_a7_action_log_media_to_pod_pages(
            action_log=action_log,
            pod_document=pod_document,
        )

        self.assertEqual(pod_line_1.map_url, 'uploads/photo1.jpg')
        self.assertEqual(pod_line_1.attachment_label, 'photo1.jpg')
        self.assertEqual(pod_line_1.soft_copy_status, 'Collected')
        self.assertEqual(pod_line_1.digital_evidence_status, 'Collected')
        mock_pod_page_model.objects.create.assert_called_once()
        self.assertEqual(pod_line_2.map_url, 'uploads/clip.mp4')
        self.assertEqual(pod_line_2.attachment_label, 'clip.mp4')


class SyncA7PodEvidenceAttachmentsTests(TestCase):
    @patch('iroad_tenants.operation_runtime.pod_action._sync_a7_action_log_media_to_pod_pages')
    @patch('iroad_tenants.operation_runtime.pod_action._find_existing_pod_for_source')
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument')
    def test_finds_pod_and_syncs_after_mobile_media_persist(
        self,
        mock_document_model,
        mock_find_pod,
        mock_sync,
    ):
        action_log = MagicMock()
        action_log.operation_action = SimpleNamespace(action_code='A7', english_label='Upload POD')
        shipment = MagicMock()
        shipment.pk = 'shipment-1'
        action_log.shipment = shipment
        source_document = MagicMock()
        mock_document_model.objects.filter.return_value.order_by.return_value.first.return_value = (
            source_document
        )
        pod_document = MagicMock()
        pod_document.source_document = source_document
        mock_find_pod.return_value = pod_document

        sync_a7_pod_evidence_attachments(action_log=action_log, shipment=shipment)

        mock_sync.assert_called_once_with(
            action_log=action_log,
            pod_document=pod_document,
            source_document=source_document,
        )


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
        document.save.assert_called_once()
        update_fields = document.save.call_args.kwargs.get('update_fields', [])
        self.assertIn('status', update_fields)
        self.assertEqual(document.status, mock_document_model.Status.VERIFIED)
        mock_refresh.assert_called_once_with(shipment)


class BirthPodFromActionLogTests(TestCase):
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument')
    def test_allocate_unique_pod_record_no_skips_existing(self, mock_document_model):
        mock_document_model.objects.filter.return_value.exists.side_effect = [True, False]
        with patch(
            'iroad_tenants.views._next_auto_number_for_form',
            side_effect=[('POD-0043', 43), ('POD-0044', 44)],
        ):
            record_no, record_sequence = _allocate_unique_pod_record_no()
        self.assertEqual(record_no, 'POD-0044')
        self.assertEqual(record_sequence, 44)

    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument')
    def test_find_existing_pod_by_source_document(self, mock_document_model):
        source = MagicMock(pk='dn-1')
        existing = MagicMock()
        mock_document_model.objects.filter.return_value.first.return_value = existing
        result = _find_existing_pod_for_source(shipment=MagicMock(), source_document=source)
        self.assertIs(result, existing)
        mock_document_model.objects.filter.assert_called_once_with(
            source_document_id='dn-1',
        )

    @patch('iroad_tenants.operation_runtime.pod_action.apply_a7_shipment_pod_type_classification')
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentPodPage')
    @patch('iroad_tenants.operation_runtime.pod_action._find_existing_pod_for_source')
    @patch('iroad_tenants.operation_runtime.pod_action.TenantShipmentDocument')
    def test_birth_pod_returns_existing_without_save(
        self,
        mock_document_model,
        mock_find_existing,
        mock_pod_page_model,
        mock_classify,
    ):
        shipment = MagicMock()
        shipment.booking_id = None
        action_log = MagicMock()
        action_log.shipment = shipment
        action_log.operation_action = SimpleNamespace(action_code='A7')
        source_document = MagicMock(pk='dn-1')
        mock_document_model.objects.filter.return_value.order_by.return_value.first.return_value = (
            source_document
        )
        existing_pod = MagicMock()
        mock_find_existing.return_value = existing_pod

        result = birth_pod_from_action_log(action_log)

        self.assertIs(result, existing_pod)
        mock_classify.assert_not_called()
