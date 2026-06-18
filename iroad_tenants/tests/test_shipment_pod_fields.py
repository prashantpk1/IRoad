"""Shipment POD field resolution for portal create/edit saves."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from iroad_tenants.views import _resolve_shipment_pod_fields_for_save
from tenant_workspace.models import TenantShipment


class ResolveShipmentPodFieldsTests(TestCase):
    def _request(self, pod_doc_count: str = '0'):
        request = MagicMock()
        request.POST = {'pod_doc_count': pod_doc_count}
        return request

    def test_edit_keeps_existing_pod_status_and_prefers_posted_pod_type(self):
        shipment = SimpleNamespace(
            pod_type=TenantShipment.PodType.DIGITAL,
            pod_status=TenantShipment.PodStatus.COMPLETED,
            pod_doc_count=2,
        )
        pod_type, pod_status, pod_doc_count = _resolve_shipment_pod_fields_for_save(
            shipment_form_data={'pod_type': 'Hard Copy', 'pod_status': 'Not Completed'},
            matched_line={'pod_type': TenantShipment.PodType.DIGITAL, 'pod_status': 'Not Completed'},
            request=self._request(),
            is_edit=True,
            existing_shipment=shipment,
        )
        self.assertEqual(pod_type, TenantShipment.PodType.HARD)
        self.assertEqual(pod_status, TenantShipment.PodStatus.COMPLETED)
        self.assertEqual(pod_doc_count, 2)

    def test_create_prefers_posted_pod_type_and_defaults_status_from_line(self):
        pod_type, pod_status, _pod_doc_count = _resolve_shipment_pod_fields_for_save(
            shipment_form_data={'pod_type': 'Hard Copy', 'pod_status': 'Not Completed'},
            matched_line={'pod_type': TenantShipment.PodType.DIGITAL, 'pod_status': 'Not Completed'},
            request=self._request(),
            is_edit=False,
        )
        self.assertEqual(pod_type, TenantShipment.PodType.HARD)
        self.assertEqual(pod_status, TenantShipment.PodStatus.NOT_COMPLETED)

    def test_create_falls_back_to_booking_line_when_form_blank(self):
        pod_type, pod_status, _pod_doc_count = _resolve_shipment_pod_fields_for_save(
            shipment_form_data={'pod_type': '', 'pod_status': ''},
            matched_line={'pod_type': TenantShipment.PodType.SOFT, 'pod_status': 'Not Completed'},
            request=self._request(),
            is_edit=False,
        )
        self.assertEqual(pod_type, TenantShipment.PodType.SOFT)
        self.assertEqual(pod_status, TenantShipment.PodStatus.NOT_COMPLETED)
