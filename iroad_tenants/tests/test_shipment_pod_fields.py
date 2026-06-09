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

    def test_edit_prefers_posted_pod_type_over_booking_line(self):
        shipment = SimpleNamespace(
            pod_type=TenantShipment.PodType.DIGITAL,
            pod_status=TenantShipment.PodStatus.PENDING,
            pod_doc_count=2,
        )
        pod_type, pod_status, pod_doc_count = _resolve_shipment_pod_fields_for_save(
            shipment_form_data={'pod_type': 'Hard', 'pod_status': 'Compliant'},
            matched_line={'pod_type': TenantShipment.PodType.DIGITAL, 'pod_status': 'Pending'},
            request=self._request(),
            is_edit=True,
            existing_shipment=shipment,
        )
        self.assertEqual(pod_type, TenantShipment.PodType.HARD)
        self.assertEqual(pod_status, TenantShipment.PodStatus.COMPLIANT)
        self.assertEqual(pod_doc_count, 2)

    def test_create_prefers_posted_pod_type_over_booking_line(self):
        pod_type, pod_status, _pod_doc_count = _resolve_shipment_pod_fields_for_save(
            shipment_form_data={'pod_type': 'Hard', 'pod_status': 'Pending'},
            matched_line={'pod_type': TenantShipment.PodType.DIGITAL, 'pod_status': 'Pending'},
            request=self._request(),
            is_edit=False,
        )
        self.assertEqual(pod_type, TenantShipment.PodType.HARD)
        self.assertEqual(pod_status, TenantShipment.PodStatus.PENDING)

    def test_create_falls_back_to_booking_line_when_form_blank(self):
        pod_type, pod_status, _pod_doc_count = _resolve_shipment_pod_fields_for_save(
            shipment_form_data={'pod_type': '', 'pod_status': ''},
            matched_line={'pod_type': TenantShipment.PodType.SOFT, 'pod_status': 'Pending'},
            request=self._request(),
            is_edit=False,
        )
        self.assertEqual(pod_type, TenantShipment.PodType.SOFT)
        self.assertEqual(pod_status, TenantShipment.PodStatus.PENDING)
