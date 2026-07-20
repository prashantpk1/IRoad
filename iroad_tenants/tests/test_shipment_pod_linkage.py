"""Portal Shipment POD shipment dropdown includes completed/closed legs."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from tenant_workspace.models import TenantShipment


class ShipmentPodLinkageQuerysetTests(TestCase):
    @patch('iroad_tenants.views.TenantShipment')
    def test_linkage_queryset_excludes_cancelled_only(self, mock_shipment_model):
        from iroad_tenants.views import _tenant_shipment_pod_linkage_shipments_queryset

        cancelled = mock_shipment_model.ShipmentStatus.CANCELLED
        chain = MagicMock()
        mock_shipment_model.objects.select_related.return_value = chain
        chain.exclude.return_value = chain
        chain.order_by.return_value = chain
        chain.__getitem__.return_value = []

        _tenant_shipment_pod_linkage_shipments_queryset()

        chain.exclude.assert_called_once_with(shipment_status=cancelled)

    @patch('iroad_tenants.views._tenant_shipment_pod_linkage_shipments_queryset')
    @patch('iroad_tenants.views._normalize_shipment_pod_type')
    @patch('iroad_tenants.views.normalize_operation_pod_status')
    def test_linkage_options_include_completed_shipment(
        self,
        mock_normalize_pod_status,
        mock_normalize_pod_type,
        mock_linkage_qs,
    ):
        from iroad_tenants.views import _tenant_shipment_pod_linkage_options

        shipment_id = uuid4()
        booking = SimpleNamespace(booking_no='BK-0001', pod_type='Digital')
        shipment = SimpleNamespace(
            pk=shipment_id,
            booking_id=uuid4(),
            booking=booking,
            shipment_no='SH-0010',
            booking_item_ref='SV-0001',
            pod_type='Digital',
            pod_status=TenantShipment.PodStatus.COMPLETED,
            pod_doc_count=1,
        )
        mock_linkage_qs.return_value = [shipment]
        mock_normalize_pod_type.side_effect = lambda value, default='': value or default
        mock_normalize_pod_status.return_value = TenantShipment.PodStatus.COMPLETED

        rows = _tenant_shipment_pod_linkage_options()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['shipment_no'], 'SH-0010')
        self.assertEqual(rows[0]['pod_status'], TenantShipment.PodStatus.COMPLETED)


class ShipmentPodActionLogOptionTests(TestCase):
    @patch('iroad_tenants.shipment_pod_form.action_log_attachment_meta', return_value=('', ''))
    @patch('iroad_tenants.shipment_pod_form.action_log_attachment_storage_path', return_value='')
    @patch('iroad_tenants.shipment_pod_form.action_log_map_url', return_value='')
    @patch(
        'iroad_tenants.operation_runtime.action_master_catalog.exclude_admin_hidden_system_logs',
    )
    @patch('iroad_tenants.shipment_pod_form.TenantOperationActionLog')
    def test_action_log_options_exclude_system_pod_verify_rows(
        self,
        mock_log_model,
        mock_exclude,
        _mock_map_url,
        _mock_storage_path,
        _mock_attachment_meta,
    ):
        from iroad_tenants.shipment_pod_form import action_log_option_rows

        chain = MagicMock()
        mock_log_model.objects.select_related.return_value = chain
        chain.prefetch_related.return_value = chain
        chain.order_by.return_value = chain
        mock_exclude.return_value = chain
        chain.filter.return_value = chain
        chain.__getitem__.return_value = []

        action_log_option_rows(shipment=SimpleNamespace(pk=uuid4()))

        mock_exclude.assert_called_once_with(chain)
